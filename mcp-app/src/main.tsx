function paint(msg: string, color = "#888") {
  const el = document.getElementById("root")
  if (el) el.innerHTML = `<pre style="margin:0;padding:16px;font:12px/1.5 ui-monospace,monospace;color:${color};white-space:pre-wrap;word-break:break-word">${msg}</pre>`
}

function pokeSize() {
  try {
    const h = Math.max(520, document.documentElement.scrollHeight)
    window.parent.postMessage(
      { jsonrpc: "2.0", method: "ui/notifications/size-changed", params: { width: window.innerWidth, height: h } },
      "*",
    )
  } catch {}
}

paint("Booting…")
pokeSize()
setInterval(pokeSize, 800)

window.addEventListener("error", (e) => {
  paint("JS error: " + (e.message || String(e.error)) + "\n" + ((e.error && e.error.stack) || ""), "#c00")
})
window.addEventListener("unhandledrejection", (e) => {
  paint("Promise rejected: " + String((e as PromiseRejectionEvent).reason), "#c00")
})

import("./boot")
  .then((m) => m.start(paint))
  .catch((err) => paint("Import failed: " + String(err) + "\n" + (err?.stack || ""), "#c00"))
