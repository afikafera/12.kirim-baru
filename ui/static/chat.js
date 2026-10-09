"use strict";

const messagesElement = document.getElementById("messages");
const statusElement = document.getElementById("status");
const promptElement = document.getElementById("prompt");
const sendButton = document.getElementById("send");
const newChatButton = document.getElementById("new-chat");
const emptyStateElement = document.getElementById("empty-state");
const chatForm = document.getElementById("chat-form");
const logoutButton = document.getElementById("logout");
const identityElement = document.getElementById("identity");
const modelPicker = document.getElementById("model-picker");
const modelTrigger = document.getElementById("model-trigger");
const selectedModelElement = document.getElementById("selected-model");
const modelMenu = document.getElementById("model-menu");
const modelSearch = document.getElementById("model-search");
const modelOptions = document.getElementById("model-options");
const modelState = document.getElementById("model-state");
const conversationListElement = document.getElementById("conversation-list");
const conversationStateElement = document.getElementById("conversation-state");
const MODEL_STORAGE_KEY = "aran.selectedModel";
let messages = [];
let availableModels = [];
let selectedModel = null;
let activeConversationId = null;
let conversations = [];
let conversationButtons = [];
let authenticated = false;
let busy = false;
let loadingConversation = false;
let navigationGeneration = 0;
let conversationListGeneration = 0;
let messageActionButtons = [];

function showStatus(text) {
  statusElement.textContent = text;
}

function updateControls() {
  const blocked = busy || loadingConversation;
  promptElement.disabled = !authenticated || blocked;
  sendButton.disabled = !authenticated || blocked;
  newChatButton.disabled = !authenticated || blocked;
  for (const button of conversationButtons) button.disabled = blocked;
  for (const button of messageActionButtons) button.disabled = !authenticated || blocked;
}

function contentForDisplay(content) {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content.map(part => {
      if (typeof part === "string") return part;
      if (part && typeof part.text === "string") return part.text;
      try { return JSON.stringify(part); } catch (_) { return ""; }
    }).filter(Boolean).join("\n");
  }
  if (content && typeof content === "object") {
    try { return JSON.stringify(content, null, 2); } catch (_) { return ""; }
  }
  return content == null ? "" : String(content);
}

const ACTION_ICONS = {
  copy: '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><rect x="8" y="8" width="12" height="12" rx="2"></rect><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"></path></svg>',
  regenerate: '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M20 7v5h-5"></path><path d="M19 12a7 7 0 0 0-12-4L4 11"></path><path d="M4 17v-5h5"></path><path d="M5 12a7 7 0 0 0 12 4l3-3"></path></svg>'
};

function createMessageAction(label, icon, onClick, className = "") {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `message-action ${className}`.trim();
  button.setAttribute("aria-label", label);
  button.title = label;
  button.innerHTML = icon;
  button.disabled = !authenticated || busy || loadingConversation;
  button.addEventListener("click", onClick);
  messageActionButtons.push(button);
  return button;
}

async function copyVisibleMessage(body, button) {
  const originalLabel = button.getAttribute("aria-label");
  try {
    if (!navigator.clipboard?.writeText) throw new Error("Clipboard API unavailable");
    await navigator.clipboard.writeText(body.textContent);
    button.setAttribute("aria-label", "Tersalin");
    button.title = "Tersalin";
    showStatus("Pesan disalin.");
    window.setTimeout(() => {
      button.setAttribute("aria-label", originalLabel);
      button.title = originalLabel;
      if (statusElement.textContent === "Pesan disalin.") showStatus("");
    }, 1400);
  } catch (_) {
    showStatus("Clipboard tidak tersedia.");
  }
}

function addMessage(role, content) {
  const item = document.createElement("li");
  item.className = role;
  const label = document.createElement("strong");
  label.textContent = role === "user" ? "Anda" : "ARAN";
  const body = document.createElement("p");
  body.textContent = contentForDisplay(content);
  const actions = document.createElement("div");
  actions.className = "message-actions";
  actions.setAttribute("role", "group");
  actions.setAttribute("aria-label", role === "user" ? "Aksi pesan Anda" : "Aksi jawaban ARAN");
  const copyButton = createMessageAction(
    "Salin pesan",
    ACTION_ICONS.copy,
    () => copyVisibleMessage(body, copyButton),
    "message-action-copy"
  );
  actions.append(copyButton);
  if (role === "assistant") {
    const messageIndex = messagesElement.children.length;
    actions.append(createMessageAction(
      "Buat ulang jawaban",
      ACTION_ICONS.regenerate,
      () => regenerateMessage(messageIndex),
      "message-action-regenerate"
    ));
  }
  item.append(label, body, actions);
  messagesElement.append(item);
  emptyStateElement.hidden = true;
  item.scrollIntoView({ block: "end" });
  return item;
}

async function regenerateMessage(assistantIndex) {
  if (busy || loadingConversation || !authenticated || !activeConversationId) return;
  if (messages[assistantIndex]?.role !== "assistant") return;
  let userIndex = assistantIndex - 1;
  while (userIndex >= 0 && messages[userIndex].role !== "user") userIndex -= 1;
  if (userIndex < 0) return;

  const requestMessages = messages.slice(0, userIndex + 1);
  const userContent = requestMessages[requestMessages.length - 1].content;
  const conversationAtSubmit = activeConversationId;
  const viewGeneration = navigationGeneration;
  const payload = { messages: requestMessages };
  if (selectedModel) payload.model = selectedModel;
  payload.conversation_id = conversationAtSubmit;

  busy = true;
  updateControls();
  showStatus("ARAN sedang membuat jawaban baru...");
  try {
    const response = await fetch("/chat/completions", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (response.status === 401) {
      redirectToLogin();
      return;
    }
    if (!response.ok) throw new Error("Regeneration request failed");
    const result = await response.json();
    const answer = result.choices?.[0]?.message?.content;
    if (typeof answer !== "string" || result.conversation_id !== conversationAtSubmit) {
      throw new Error("Invalid regeneration response");
    }
    if (viewGeneration !== navigationGeneration || activeConversationId !== conversationAtSubmit) {
      await loadConversations();
      return;
    }

    // The current API persists exchanges by appending a user/assistant pair.
    messages = [...messages, { role: "user", content: userContent }, { role: "assistant", content: answer }];
    addMessage("user", userContent);
    addMessage("assistant", answer);
    showStatus("Jawaban baru ditambahkan ke percakapan.");
    await loadConversations();
  } catch (_) {
    if (viewGeneration === navigationGeneration) showStatus("Jawaban baru gagal dibuat. Coba lagi.");
  } finally {
    busy = false;
    updateControls();
  }
}

function redirectToLogin() {
  window.location.replace("/login");
}

function startNewChat() {
  if (busy || loadingConversation || !authenticated) return;
  navigationGeneration += 1;
  activeConversationId = null;
  messages = [];
  messagesElement.replaceChildren();
  messageActionButtons = [];
  promptElement.value = "";
  showStatus("");
  emptyStateElement.hidden = false;
  renderConversations(conversations);
  promptElement.focus();
}

newChatButton.addEventListener("click", startNewChat);

function savedModel() {
  try {
    return window.localStorage.getItem(MODEL_STORAGE_KEY);
  } catch (_) {
    return null;
  }
}

function saveModel(model) {
  try {
    if (model) window.localStorage.setItem(MODEL_STORAGE_KEY, model);
    else window.localStorage.removeItem(MODEL_STORAGE_KEY);
  } catch (_) {
    // The selection remains active for this page even if storage is blocked.
  }
}

function closeModelMenu() {
  modelMenu.hidden = true;
  modelTrigger.setAttribute("aria-expanded", "false");
}

function selectModel(model) {
  selectedModel = model;
  selectedModelElement.textContent = model;
  saveModel(model);
  renderModelOptions(modelSearch.value);
  closeModelMenu();
}

function renderModelOptions(query = "") {
  modelOptions.replaceChildren();
  const normalizedQuery = query.trim().toLowerCase();
  const matches = availableModels.filter(model =>
    model.toLowerCase().includes(normalizedQuery)
  );

  if (matches.length === 0) {
    modelState.hidden = false;
    modelState.textContent = availableModels.length
      ? "Model tidak ditemukan."
      : "Belum ada model yang dikonfigurasi.";
    return;
  }

  modelState.hidden = true;
  for (const model of matches) {
    const item = document.createElement("li");
    const option = document.createElement("button");
    option.type = "button";
    option.className = "model-option";
    option.setAttribute("role", "option");
    option.setAttribute("aria-selected", String(model === selectedModel));
    const mark = document.createElement("span");
    mark.className = "model-mark";
    mark.setAttribute("aria-hidden", "true");
    mark.textContent = model === selectedModel ? "✓" : "";
    const name = document.createElement("span");
    name.textContent = model;
    option.append(mark, name);
    option.addEventListener("click", () => selectModel(model));
    item.append(option);
    modelOptions.append(item);
  }
}

async function loadModels() {
  try {
    const response = await fetch("/models", {
      credentials: "same-origin",
      cache: "no-store"
    });
    if (response.status === 401) {
      redirectToLogin();
      return;
    }
    if (!response.ok) throw new Error("Model list request failed");

    const result = await response.json();
    const ids = Array.isArray(result.data)
      ? result.data
          .map(item => item && typeof item.id === "string" ? item.id.trim() : "")
          .filter(Boolean)
      : [];
    availableModels = [...new Set(ids)];

    const saved = savedModel();
    selectedModel = availableModels.includes(saved)
      ? saved
      : (availableModels[0] || null);
    saveModel(selectedModel);
    selectedModelElement.textContent = selectedModel || "Model tidak tersedia";
    modelTrigger.disabled = false;
    renderModelOptions();
  } catch (_) {
    availableModels = [];
    selectedModel = null;
    selectedModelElement.textContent = "Model tidak tersedia";
    modelTrigger.disabled = false;
    modelState.hidden = false;
    modelState.textContent = "Daftar model gagal dimuat.";
    modelOptions.replaceChildren();
  }
}

function conversationGroupLabel(conversation) {
  const date = new Date(conversation.updated_at || conversation.created_at);
  if (Number.isNaN(date.getTime())) return "Older";
  const now = new Date();
  const todayOrdinal = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  const dateOrdinal = Date.UTC(date.getFullYear(), date.getMonth(), date.getDate());
  const daysAgo = Math.floor((todayOrdinal - dateOrdinal) / 86400000);
  if (daysAgo <= 0) return "Today";
  if (daysAgo === 1) return "Yesterday";
  if (daysAgo <= 7) return "Previous 7 days";
  return "Older";
}

function renderConversations(items) {
  conversationListElement.replaceChildren();
  conversationButtons = [];
  const groups = new Map();
  for (const conversation of items) {
    if (!conversation || typeof conversation.id !== "string") continue;
    const label = conversationGroupLabel(conversation);
    if (!groups.has(label)) groups.set(label, []);
    groups.get(label).push(conversation);
  }

  if (groups.size === 0) {
    conversationStateElement.hidden = false;
    conversationStateElement.textContent = "Belum ada percakapan.";
    updateControls();
    return;
  }

  conversationStateElement.hidden = true;
  for (const [label, group] of groups) {
    const groupItem = document.createElement("li");
    groupItem.className = "conversation-group";
    const heading = document.createElement("h3");
    heading.textContent = label;
    const groupList = document.createElement("ul");
    groupList.className = "conversation-group-list";
    for (const conversation of group) {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "conversation-item";
      button.textContent = typeof conversation.title === "string" ? conversation.title : "";
      button.setAttribute("aria-current", String(conversation.id === activeConversationId));
      button.addEventListener("click", () => openConversation(conversation.id));
      item.append(button);
      groupList.append(item);
      conversationButtons.push(button);
    }
    groupItem.append(heading, groupList);
    conversationListElement.append(groupItem);
  }
  updateControls();
}

async function loadConversations() {
  const generation = ++conversationListGeneration;
  try {
    const response = await fetch("/conversations", {
      credentials: "same-origin",
      cache: "no-store"
    });
    if (response.status === 401) {
      redirectToLogin();
      return false;
    }
    if (!response.ok) throw new Error("Conversation list request failed");
    const result = await response.json();
    if (generation !== conversationListGeneration) return false;
    if (!Array.isArray(result.data)) throw new Error("Invalid conversation list");
    conversations = result.data;
    renderConversations(conversations);
    return true;
  } catch (_) {
    if (generation === conversationListGeneration) {
      conversationStateElement.hidden = false;
      conversationStateElement.textContent = "Riwayat percakapan gagal dimuat.";
    }
    return false;
  }
}

async function openConversation(conversationId) {
  if (!authenticated || busy || loadingConversation || !conversationId) return;
  if (conversationId === activeConversationId) return;
  const generation = ++navigationGeneration;
  loadingConversation = true;
  conversationStateElement.hidden = false;
  conversationStateElement.textContent = "Memuat percakapan…";
  updateControls();
  try {
    const response = await fetch(`/conversations/${encodeURIComponent(conversationId)}`, {
      credentials: "same-origin",
      cache: "no-store"
    });
    if (response.status === 401) {
      redirectToLogin();
      return;
    }
    if (!response.ok) throw new Error("Conversation request failed");
    const conversation = await response.json();
    if (generation !== navigationGeneration) return;
    if (conversation.id !== conversationId || !Array.isArray(conversation.messages)) {
      throw new Error("Invalid conversation response");
    }

    const loadedMessages = conversation.messages
      .filter(message => message && (message.role === "user" || message.role === "assistant"))
      .map(message => ({ role: message.role, content: message.content }));
    activeConversationId = conversationId;
    messages = loadedMessages;
    messagesElement.replaceChildren();
    messageActionButtons = [];
    for (const message of messages) addMessage(message.role, message.content);
    emptyStateElement.hidden = messages.length > 0;
    promptElement.value = "";
    showStatus("");

    if (typeof conversation.model === "string" && conversation.model) {
      if (availableModels.includes(conversation.model)) {
        selectModel(conversation.model);
      } else {
        showStatus("Model percakapan tidak tersedia di registry saat ini.");
      }
    }
    renderConversations(conversations);
  } catch (_) {
    if (generation === navigationGeneration) {
      conversationStateElement.hidden = false;
      conversationStateElement.textContent = "Percakapan gagal dimuat.";
      showStatus("Percakapan gagal dimuat. Tampilan saat ini tetap dipertahankan.");
    }
  } finally {
    if (generation === navigationGeneration) {
      loadingConversation = false;
      updateControls();
    }
  }
}

async function checkSession() {
  try {
    const response = await fetch("/auth/me", {
      credentials: "same-origin",
      cache: "no-store"
    });
    if (response.status === 401) {
      redirectToLogin();
      return;
    }
    if (!response.ok) throw new Error("Session check failed");
    const identity = await response.json();
    identityElement.textContent = identity.username;
    authenticated = true;
    updateControls();
    await loadModels();
    await loadConversations();
    promptElement.focus();
  } catch (_) {
    showStatus("Tidak dapat memeriksa session. Muat ulang halaman.");
  }
}

modelTrigger.addEventListener("click", () => {
  const opening = modelMenu.hidden;
  modelMenu.hidden = !opening;
  modelTrigger.setAttribute("aria-expanded", String(opening));
  if (opening) {
    modelSearch.value = "";
    renderModelOptions();
    modelSearch.focus();
  }
});

modelSearch.addEventListener("input", () => {
  renderModelOptions(modelSearch.value);
});

document.addEventListener("click", event => {
  if (!modelPicker.contains(event.target)) closeModelMenu();
});

document.addEventListener("keydown", event => {
  if (event.key === "Escape") closeModelMenu();
});

chatForm.addEventListener("submit", async event => {
  event.preventDefault();
  const prompt = promptElement.value.trim();
  if (!prompt || busy || loadingConversation || !authenticated) return;
  busy = true;
  updateControls();
  showStatus("ARAN sedang menjawab...");
  const viewGeneration = navigationGeneration;
  const conversationAtSubmit = activeConversationId;
  const userItem = addMessage("user", prompt);
  const requestMessages = [...messages, { role: "user", content: prompt }];
  promptElement.value = "";
  try {
    const payload = { messages: requestMessages };
    if (selectedModel) payload.model = selectedModel;
    if (conversationAtSubmit !== null) payload.conversation_id = conversationAtSubmit;
    const response = await fetch("/chat/completions", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (response.status === 401) {
      userItem.remove();
      promptElement.value = prompt;
      emptyStateElement.hidden = messagesElement.children.length > 0;
      redirectToLogin();
      return;
    }
    if (!response.ok) throw new Error("Chat request failed");
    const result = await response.json();
    const answer = result.choices?.[0]?.message?.content;
    const responseConversationId = result.conversation_id;
    if (typeof answer !== "string" || typeof responseConversationId !== "string") {
      throw new Error("Invalid chat response");
    }
    if (conversationAtSubmit !== null && responseConversationId !== conversationAtSubmit) {
      throw new Error("Chat response conversation mismatch");
    }
    if (viewGeneration !== navigationGeneration) {
      await loadConversations();
      return;
    }

    activeConversationId = responseConversationId;
    messages = [...requestMessages, { role: "assistant", content: answer }];
    addMessage("assistant", answer);
    renderConversations(conversations);
    showStatus("");
    await loadConversations();
  } catch (_) {
    if (viewGeneration === navigationGeneration) {
      userItem.remove();
      emptyStateElement.hidden = messagesElement.children.length > 0;
      promptElement.value = prompt;
      showStatus("Jawaban gagal dimuat. Coba lagi.");
    }
  } finally {
    busy = false;
    updateControls();
    if (authenticated) promptElement.focus();
  }
});

logoutButton.addEventListener("click", async () => {
  logoutButton.disabled = true;
  try {
    const response = await fetch("/auth/logout", {
      method: "POST",
      credentials: "same-origin"
    });
    if (!response.ok && response.status !== 401) {
      throw new Error("Logout failed");
    }
    messages = [];
    messageActionButtons = [];
    activeConversationId = null;
    redirectToLogin();
  } catch (_) {
    showStatus("Gagal keluar. Coba lagi.");
    logoutButton.disabled = false;
  }
});

updateControls();
checkSession();
