"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor(id = "") {
    this.id = id;
    this.children = [];
    this.listeners = {};
    this.attributes = {};
    this.value = "";
    this.textContent = "";
    this.hidden = false;
    this.disabled = false;
  }

  addEventListener(type, callback) {
    (this.listeners[type] ||= []).push(callback);
  }

  async dispatch(type, event = {}) {
    for (const callback of this.listeners[type] || []) {
      await callback({ preventDefault() {}, target: this, ...event });
    }
  }

  append(...children) {
    this.children.push(...children);
  }

  replaceChildren(...children) {
    this.children = children;
  }

  setAttribute(name, value) {
    this.attributes[name] = value;
  }

  focus() {}
  scrollIntoView() {}
  remove() {}

  contains(target) {
    return this === target || this.children.some(child => child.contains(target));
  }
}

async function loadPage(modelIds, storage = new Map(), failModels = false) {
  const ids = [
    "messages", "status", "prompt", "send", "new-chat", "empty-state",
    "chat-form", "logout", "identity", "model-picker", "model-trigger",
    "selected-model", "model-menu", "model-search", "model-options",
    "model-state", "conversation-list", "conversation-state",
  ];
  const elements = new Map(ids.map(id => [id, new Element(id)]));
  elements.get("model-menu").hidden = true;
  elements.get("model-trigger").disabled = true;
  elements.get("prompt").disabled = true;
  elements.get("send").disabled = true;
  const documentListeners = {};
  const requests = [];
  const navigation = [];
  const document = {
    getElementById: id => elements.get(id),
    createElement: () => new Element(),
    addEventListener(type, callback) {
      (documentListeners[type] ||= []).push(callback);
    },
  };
  const localStorage = {
    getItem: key => storage.get(key) || null,
    setItem: (key, value) => storage.set(key, value),
    removeItem: key => storage.delete(key),
  };
  const window = {
    localStorage,
    location: { replace: path => navigation.push(path) },
  };
  const fetch = async (url, options = {}) => {
    requests.push({ url, options });
    if (url === "/auth/me") {
      return { status: 200, ok: true, json: async () => ({ username: "tester" }) };
    }
    if (url === "/models") {
      if (failModels) return { status: 503, ok: false };
      return {
        status: 200,
        ok: true,
        json: async () => ({
          object: "list",
          data: modelIds.map(id => ({ id, object: "model" })),
        }),
      };
    }
    if (url === "/chat/completions") {
      return {
        status: 200,
        ok: true,
        json: async () => ({
          choices: [{ message: { content: "test answer" } }],
        }),
      };
    }
    throw new Error(`Unexpected request: ${url}`);
  };

  const source = fs.readFileSync("ui/static/chat.js", "utf8");
  vm.runInNewContext(source, { document, window, fetch });
  await new Promise(resolve => setImmediate(resolve));
  return { elements, requests, navigation, documentListeners, storage };
}

async function run() {
  const fourModels = ["9routerpc", "deepseek-chat", "omniroute", "poolside"];
  const page = await loadPage(fourModels);
  const e = page.elements;
  assert.equal(e.get("selected-model").textContent, "9routerpc");
  assert.equal(e.get("model-options").children.length, 4);
  assert.equal(e.get("prompt").disabled, false);

  await e.get("model-trigger").dispatch("click");
  assert.equal(e.get("model-menu").hidden, false);
  const poolsideOption = e.get("model-options").children
    .map(item => item.children[0])
    .find(option => option.children[1].textContent === "poolside");
  assert.ok(poolsideOption);
  await poolsideOption.dispatch("click");
  assert.equal(e.get("selected-model").textContent, "poolside");
  assert.equal(page.storage.get("aran.selectedModel"), "poolside");

  e.get("prompt").value = "halo";
  await e.get("chat-form").dispatch("submit");
  const chatRequest = page.requests.find(request => request.url === "/chat/completions");
  assert.equal(JSON.parse(chatRequest.options.body).model, "poolside");

  const addedModel = await loadPage([...fourModels, "new-provider"]);
  assert.equal(addedModel.elements.get("model-options").children.length, 5);

  const empty = await loadPage([]);
  assert.equal(empty.elements.get("prompt").disabled, false);
  await empty.elements.get("model-trigger").dispatch("click");
  assert.match(empty.elements.get("model-state").textContent, /Belum ada model/);

  const failed = await loadPage([], new Map(), true);
  assert.equal(failed.elements.get("prompt").disabled, false);
  assert.match(failed.elements.get("model-state").textContent, /gagal dimuat/);

  const html = fs.readFileSync("ui/chat.html", "utf8");
  const script = fs.readFileSync("ui/static/chat.js", "utf8");
  assert.doesNotMatch(html + script, /deepseek-chat|omniroute|poolside|9routerpc/);
  console.log("model picker tests: PASS (dynamic list, add model, empty/error, selected request, persistence)");
}

run().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
