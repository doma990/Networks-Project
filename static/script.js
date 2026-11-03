const form = document.querySelector("#chat-form");
const status = document.querySelector("#status");
const messages = document.querySelector("#messages");
const sendButton = document.querySelector("#send");
const usernameInput = form.elements.namedItem("username");
const messageInput = form.elements.namedItem("message");

const scheme = location.protocol === "https:" ? "wss:" : "ws:";
const socket = new WebSocket(`${scheme}//${location.host}/ws`);

socket.addEventListener("open", () => {
    status.textContent = "Connected";
    sendButton.disabled = false;
});

socket.addEventListener("message", (event) => {
    const { username, text } = JSON.parse(event.data);
    const entry = document.createElement("li");
    entry.textContent = `${username}: ${text}`;
    messages.append(entry);
});

socket.addEventListener("close", () => {
    status.textContent = "Disconnected. Reload to try again.";
    sendButton.disabled = true;
});

form.addEventListener("submit", (event) => {
    event.preventDefault();

    const username = usernameInput.value.trim();
    const text = messageInput.value.trim();
    if (!username || !text || socket.readyState !== WebSocket.OPEN) return;

    socket.send(JSON.stringify({ username, text }));
    messageInput.value = "";
});