document.addEventListener("DOMContentLoaded", function () {
  var widget = document.querySelector(".ai-widget");
  var btn = document.getElementById("aiFab");
  var panel = document.getElementById("aiPanel");
  var closeBtn = document.getElementById("aiClose");

  var input = document.getElementById("aiInput");
  var sendBtn = document.getElementById("aiSend");
  var messages = document.getElementById("aiLog");

  if (!widget || !btn || !panel || !closeBtn) return;

  function openPanel() {
    widget.classList.add("is-open");
    panel.classList.remove("hidden");
    if (input) setTimeout(function () { input.focus(); }, 0);
  }

  function closePanel() {
    widget.classList.remove("is-open");
    panel.classList.add("hidden");
  }

  btn.addEventListener("click", function (e) {
    e.preventDefault();
    e.stopPropagation();
    if (widget.classList.contains("is-open")) closePanel();
    else openPanel();
  });

  closeBtn.addEventListener("click", function (e) {
    e.preventDefault();
    e.stopPropagation();
    closePanel();
  });

  panel.addEventListener("click", function (e) {
    e.stopPropagation();
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && widget.classList.contains("is-open")) closePanel();
  });

  if (!input || !sendBtn || !messages) return;

  function addMessage(text, who) {
    var div = document.createElement("div");
    div.className = "ai-bubble " + (who === "me" ? "me" : "bot");
    div.textContent = text;
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
    return div;
  }

  async function sendToServer(text) {
    var res = await fetch("/ai/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
    });
    return await res.json();
  }

  async function doSend() {
    var text = (input.value || "").trim();
    if (!text) return;

    addMessage(text, "me");
    input.value = "";
    sendBtn.disabled = true;

    var pending = addMessage("Typing…", "bot");

    try {
      var data = await sendToServer(text);
      pending.textContent = (data && data.reply) ? data.reply : "No reply.";
    } catch (err) {
      pending.textContent = "Server error. Check Flask logs.";
    } finally {
      sendBtn.disabled = false;
      input.focus();
    }
  }

  sendBtn.addEventListener("click", function (e) {
    e.preventDefault();
    doSend();
  });

  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter") {
      e.preventDefault();
      doSend();
    }
  });
});
