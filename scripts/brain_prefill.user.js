// ==UserScript==
// @name         WQ Alpha OS - điền biểu thức
// @namespace    wq-alpha-os.local
// @version      0.2.0
// @description  Đọc alpha_os trên đường dẫn và điền biểu thức; không tự mô phỏng hay tự nộp.
// @match        https://platform.worldquantbrain.com/simulate*
// @grant        none
// ==/UserScript==

(function () {
  "use strict";
  const encoded = new URLSearchParams(location.search).get("alpha_os");
  if (!encoded) return;

  function decode(value) {
    const padded = value + "=".repeat((4 - value.length % 4) % 4);
    const binary = atob(padded.replace(/-/g, "+").replace(/_/g, "/"));
    const bytes = Uint8Array.from(binary, character => character.charCodeAt(0));
    return JSON.parse(new TextDecoder().decode(bytes));
  }

  function notice(message, color) {
    let box = document.getElementById("alpha-os-notice");
    if (!box) {
      box = document.createElement("div");
      box.id = "alpha-os-notice";
      Object.assign(box.style, {position: "fixed", right: "16px", bottom: "16px", zIndex: 2147483647,
        padding: "12px 16px", maxWidth: "430px", color: "white", borderRadius: "8px",
        font: "13px system-ui", boxShadow: "0 4px 16px #0006"});
      document.body.appendChild(box);
    }
    box.style.background = color;
    box.textContent = message;
  }

  function nativeSet(element, value) {
    const proto = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
    if (setter) setter.call(element, value); else element.value = value;
    element.dispatchEvent(new InputEvent("input", {bubbles: true, inputType: "insertText", data: value}));
    element.dispatchEvent(new Event("change", {bubbles: true}));
  }

  function fill(expression) {
    const textareas = [...document.querySelectorAll(".monaco-editor textarea.inputarea, textarea")]
      .filter(element => element.offsetParent !== null);
    const target = textareas.find(element => element.closest(".monaco-editor")) ||
      textareas.sort((a, b) => (b.clientWidth * b.clientHeight) - (a.clientWidth * a.clientHeight))[0];
    if (target) {
      target.focus();
      if (target.closest(".monaco-editor")) {
        document.execCommand("selectAll", false);
        document.execCommand("insertText", false, expression);
      } else nativeSet(target, expression);
      return true;
    }
    const editable = [...document.querySelectorAll(".cm-content, [contenteditable='true']")]
      .find(element => element.offsetParent !== null);
    if (editable) {
      editable.focus();
      document.execCommand("selectAll", false);
      document.execCommand("insertText", false, expression);
      editable.dispatchEvent(new InputEvent("input", {bubbles: true, inputType: "insertText", data: expression}));
      return true;
    }
    return false;
  }

  let payload;
  try { payload = decode(encoded); }
  catch (error) { notice("Alpha OS: đường dẫn bị lỗi, không giải mã được.", "#9b1c1c"); return; }

  let attempts = 0;
  const timer = setInterval(async () => {
    attempts += 1;
    if (fill(payload.expression)) {
      clearInterval(timer);
      history.replaceState(null, "", location.pathname);
      notice("Alpha OS: đã điền biểu thức. Hãy kiểm tra thiết lập rồi tự bấm mô phỏng.", "#166534");
    } else if (attempts >= 60) {
      clearInterval(timer);
      try { await navigator.clipboard.writeText(payload.expression); } catch (_) {}
      notice("Alpha OS: không tìm thấy ô soạn thảo; biểu thức đã được thử sao chép vào bộ nhớ tạm.", "#9b1c1c");
    }
  }, 500);
})();
