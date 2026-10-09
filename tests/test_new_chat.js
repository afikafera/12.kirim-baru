"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor(id = "") {
    this.id = id;
    this.className = "";
    this.children = [];
    this.listeners = {};
    this.attributes = {};
    this.value = "";
    this.textContent = "";
    this.hidden = false;
    this.disabled = false;
    this.parentElement = null;
  }
  addEventListener(type, callback) { (this.listeners[type] ||= []).push(callback); }
  async dispatch(type, event = {}) {
    if (this.disabled) return;
    for (const callback of this.listeners[type] || []) {
      await callback({ preventDefault() {}, target: this, ...event });
    }
  }
  append(...children) {
    for (const child of children) {
      child.parentElement = this;
      this.children.push(child);
    }
  }
  replaceChildren(...children) {
    for (const child of this.children) child.parentElement = null;
    this.children = [];
    this.append(...children);
  }
  setAttribute(name, value) { this.attributes[name] = value; }
  getAttribute(name) { return this.attributes[name]; }
  focus() {}
  scrollIntoView() {}
  remove() {
    if (!this.parentElement) return;
    this.parentElement.children = this.parentElement.children.filter(child => child !== this);
    this.parentElement = null;
  }
  contains(target) { return this === target || this.children.some(child => child.contains(target)); }
}

function descendants(element) {
  return element.children.flatMap(child => [child, ...descendants(child)]);
}

function makeBackend() {
  const now = new Date().toISOString();
  return {
    conversations: [
      {
        id: "conv-A", title: "Conversation A", model: "9routerpc",
        created_at: now, updated_at: now,
        messages: [
          { id: "m1", role: "user", content: "CHAT_A_TEST", created_at: now },
          { id: "m2", role: "assistant", content: "reply A", created_at: now },
        ],
      },
      {
        id: "conv-B", title: "Conversation B", model: "deepseek-chat",
        created_at: now, updated_at: now,
        messages: [
          { id: "m3", role: "user", content: "CHAT_B_TEST", created_at: now },
          { id: "m4", role: "assistant", content: "reply B", created_at: now },
        ],
      },
    ],
    nextId: 1,
  };
}

function sortedConversations(backend) {
  return [...backend.conversations].sort((a, b) =>
    String(b.updated_at).localeCompare(String(a.updated_at)) || b.id.localeCompare(a.id)
  );
}

async function loadPage({ backend = makeBackend(), storage = new Map(), failDetail = new Set(), chatGate = null } = {}) {
  const ids = [
    "messages", "status", "prompt", "send", "new-chat", "empty-state",
    "chat-form", "logout", "identity", "model-picker", "model-trigger",
    "selected-model", "model-menu", "model-search", "model-options", "model-state",
    "conversation-list", "conversation-state",
  ];
  const elements = new Map(ids.map(id => [id, new Element(id)]));
  elements.get("model-menu").hidden = true;
  elements.get("model-trigger").disabled = true;
  elements.get("prompt").disabled = true;
  elements.get("send").disabled = true;
  const requests = [];
  const navigation = [];
  const documentListeners = {};
  const document = {
    getElementById: id => elements.get(id),
    createElement: () => new Element(),
    addEventListener(type, callback) { (documentListeners[type] ||= []).push(callback); },
  };
  const window = {
    localStorage: {
      getItem: key => storage.get(key) || null,
      setItem: (key, value) => storage.set(key, value),
      removeItem: key => storage.delete(key),
    },
    location: { replace: path => navigation.push(path) },
  };

  const json = value => ({ status: 200, ok: true, json: async () => value });
  const fetch = async (url, options = {}) => {
    requests.push({ url, options });
    if (url === "/auth/me") return json({ username: "tester" });
    if (url === "/models") return json({ object: "list", data: [{ id: "9routerpc" }, { id: "deepseek-chat" }] });
    if (url === "/conversations" && (!options.method || options.method === "GET")) {
      return json({ data: sortedConversations(backend).map(({ messages, ...item }) => item) });
    }
    if (url.startsWith("/conversations/") && (!options.method || options.method === "GET")) {
      const id = decodeURIComponent(url.slice("/conversations/".length));
      if (failDetail.has(id)) return { status: 500, ok: false, json: async () => ({}) };
      const conversation = backend.conversations.find(item => item.id === id);
      return conversation ? json(structuredClone(conversation)) : { status: 404, ok: false, json: async () => ({}) };
    }
    if (url === "/chat/completions") {
      const body = JSON.parse(options.body);
      const perform = () => {
        const prompt = body.messages.at(-1).content;
        let conversation = body.conversation_id
          ? backend.conversations.find(item => item.id === body.conversation_id)
          : null;
        if (!conversation) {
          conversation = {
            id: `conv-new-${backend.nextId++}`, title: prompt.slice(0, 80),
            model: body.model, created_at: new Date().toISOString(), updated_at: new Date().toISOString(), messages: [],
          };
          backend.conversations.push(conversation);
        }
        const created = new Date().toISOString();
        conversation.messages.push(
          { id: `m${backend.nextId++}`, role: "user", content: prompt, created_at: created },
          { id: `m${backend.nextId++}`, role: "assistant", content: `answer: ${prompt}`, created_at: created },
        );
        conversation.updated_at = created;
        return json({
          conversation_id: conversation.id,
          choices: [{ message: { content: `answer: ${prompt}` } }],
        });
      };
      return chatGate ? chatGate(perform) : perform();
    }
    if (url === "/auth/logout") return { status: 200, ok: true };
    throw new Error(`Unexpected request: ${url}`);
  };

  vm.runInNewContext(fs.readFileSync("ui/static/chat.js", "utf8"), { document, window, fetch });
  for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve));
  return { elements, requests, navigation, storage, backend, documentListeners };
}

function buttonsWithClass(element, className) {
  return descendants(element).filter(item => item.className === className);
}
function visibleMessages(element) {
  return element.children.map(item => ({ role: item.className, content: item.children[1].textContent }));
}
async function chooseModel(page, model) {
  const e = page.elements;
  await e.get("model-trigger").dispatch("click");
  const option = descendants(e.get("model-options")).find(item =>
    item.className === "model-option" && item.children[1].textContent === model
  );
  assert.ok(option, `model option ${model} exists`);
  await option.dispatch("click");
}
async function submit(page, prompt) {
  page.elements.get("prompt").value = prompt;
  await page.elements.get("chat-form").dispatch("submit");
}

async function run() {
  const storage = new Map();
  const backend = makeBackend();
  const page = await loadPage({ backend, storage });
  const e = page.elements;

  // List renders from backend and preserves the API's order/group labels.
  assert.equal(page.requests.filter(request => request.url === "/conversations").length, 1);
  assert.deepEqual(buttonsWithClass(e.get("conversation-list"), "conversation-item").map(item => item.textContent), ["Conversation B", "Conversation A"]);
  assert.ok(descendants(e.get("conversation-list")).some(item => item.textContent === "Today"));

  // Selecting a conversation loads persisted messages and its model.
  const conversationAButton = buttonsWithClass(e.get("conversation-list"), "conversation-item").find(item => item.textContent === "Conversation A");
  await conversationAButton.dispatch("click");
  assert.equal(page.requests.some(request => request.url === "/conversations/conv-A"), true);
  assert.deepEqual(visibleMessages(e.get("messages")), [
    { role: "user", content: "CHAT_A_TEST" },
    { role: "assistant", content: "reply A" },
  ]);
  assert.equal(e.get("selected-model").textContent, "9routerpc");
  let currentButtons = buttonsWithClass(e.get("conversation-list"), "conversation-item");
  await currentButtons.find(item => item.textContent === "Conversation B").dispatch("click");
  assert.deepEqual(visibleMessages(e.get("messages")), [
    { role: "user", content: "CHAT_B_TEST" },
    { role: "assistant", content: "reply B" },
  ]);
  currentButtons = buttonsWithClass(e.get("conversation-list"), "conversation-item");
  await currentButtons.find(item => item.textContent === "Conversation A").dispatch("click");
  assert.deepEqual(visibleMessages(e.get("messages")), [
    { role: "user", content: "CHAT_A_TEST" },
    { role: "assistant", content: "reply A" },
  ]);

  // Failed detail load leaves the current conversation visible and selected.
  page.backend.conversations[1].title = "Conversation B";
  const failedPage = await loadPage({ backend, storage, failDetail: new Set(["conv-B"]) });
  const failedPageButtons = buttonsWithClass(failedPage.elements.get("conversation-list"), "conversation-item");
  await failedPageButtons.find(item => item.textContent === "Conversation A").dispatch("click");
  const beforeFailedLoad = visibleMessages(failedPage.elements.get("messages"));
  await failedPageButtons.find(item => item.textContent === "Conversation B").dispatch("click");
  assert.deepEqual(visibleMessages(failedPage.elements.get("messages")), beforeFailedLoad);
  assert.equal(buttonsWithClass(failedPage.elements.get("conversation-list"), "conversation-item").find(item => item.textContent === "Conversation A").getAttribute("aria-current"), "true");

  // Model choice survives New Chat; New Chat creates no server row.
  await chooseModel(page, "deepseek-chat");
  const countBeforeNewChat = backend.conversations.length;
  await e.get("new-chat").dispatch("click");
  assert.equal(e.get("messages").children.length, 0);
  assert.equal(e.get("prompt").value, "");
  assert.equal(e.get("empty-state").hidden, false);
  assert.equal(e.get("selected-model").textContent, "deepseek-chat");
  assert.equal(backend.conversations.length, countBeforeNewChat);
  assert.equal(buttonsWithClass(e.get("conversation-list"), "conversation-item")[0].getAttribute("aria-current"), "false");

  // First message omits the conversation ID and captures the response ID.
  await submit(page, "first message");
  let chatRequests = page.requests.filter(request => request.url === "/chat/completions");
  const firstBody = JSON.parse(chatRequests[0].options.body);
  assert.equal(Object.hasOwn(firstBody, "conversation_id"), false);
  assert.equal(firstBody.model, "deepseek-chat");
  const createdId = backend.conversations.find(item => item.title === "first message").id;
  assert.equal(createdId, "conv-new-1");
  assert.ok(buttonsWithClass(e.get("conversation-list"), "conversation-item").some(item => item.textContent === "first message"));
  assert.deepEqual(visibleMessages(e.get("messages")), [
    { role: "user", content: "first message" },
    { role: "assistant", content: "answer: first message" },
  ]);

  // Continuation uses the returned ID and does not duplicate old messages in storage.
  await submit(page, "second message");
  chatRequests = page.requests.filter(request => request.url === "/chat/completions");
  const secondBody = JSON.parse(chatRequests[1].options.body);
  assert.equal(secondBody.conversation_id, createdId);
  assert.deepEqual(secondBody.messages.map(message => message.content), [
    "first message", "answer: first message", "second message",
  ]);
  const persisted = backend.conversations.find(item => item.id === createdId);
  assert.deepEqual(persisted.messages.map(message => message.content), [
    "first message", "answer: first message", "second message", "answer: second message",
  ]);
  assert.equal(persisted.messages.length, 4);

  // Reload initializes from GET /conversations; opening loads history from API, not localStorage.
  const reloaded = await loadPage({ backend, storage });
  assert.equal(reloaded.requests.some(request => request.url === "/conversations"), true);
  assert.equal(reloaded.elements.get("messages").children.length, 0);
  const newConversationButton = buttonsWithClass(reloaded.elements.get("conversation-list"), "conversation-item")
    .find(item => item.textContent === "first message");
  assert.ok(newConversationButton);
  await newConversationButton.dispatch("click");
  assert.deepEqual(visibleMessages(reloaded.elements.get("messages")), [
    { role: "user", content: "first message" },
    { role: "assistant", content: "answer: first message" },
    { role: "user", content: "second message" },
    { role: "assistant", content: "answer: second message" },
  ]);
  assert.equal(reloaded.elements.get("selected-model").textContent, "deepseek-chat");

  // While a request is pending, New Chat and conversation switching are disabled.
  let resolveChat;
  const gated = await loadPage({
    backend: makeBackend(),
    chatGate: perform => new Promise(resolve => { resolveChat = () => resolve(perform()); }),
  });
  await gated.elements.get("new-chat").dispatch("click");
  gated.elements.get("prompt").value = "pending message";
  const pending = gated.elements.get("chat-form").dispatch("submit");
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(gated.elements.get("new-chat").disabled, true);
  const activeBeforeClick = visibleMessages(gated.elements.get("messages"));
  await gated.elements.get("new-chat").dispatch("click");
  await buttonsWithClass(gated.elements.get("conversation-list"), "conversation-item")[0].dispatch("click");
  assert.deepEqual(visibleMessages(gated.elements.get("messages")), activeBeforeClick);
  resolveChat();
  await pending;
  assert.equal(gated.backend.conversations.some(item => item.title === "pending message"), true);
  assert.deepEqual(visibleMessages(gated.elements.get("messages")).map(item => item.content), [
    "pending message", "answer: pending message",
  ]);

  // Existing auth/logout and static structure remain intact.
  await e.get("logout").dispatch("click");
  assert.deepEqual(page.navigation, ["/login"]);
  assert.equal(page.requests.filter(request => request.url === "/auth/logout").length, 1);
  const html = fs.readFileSync("ui/chat.html", "utf8");
  assert.match(html, /<aside class="sidebar"/);
  assert.match(html, /id="conversation-list"/);
  assert.match(html, /id="new-chat"/);

  console.log("conversation sidebar tests: PASS (list, select, new chat, returned ID, continuation, refresh, model, load failure, race guard, logout)");
}

run().catch(error => { console.error(error); process.exitCode = 1; });
