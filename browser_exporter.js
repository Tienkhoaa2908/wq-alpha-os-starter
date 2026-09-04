(() => {
  function clean(x) {
    return (x || "").replace(/\s+/g, " ").replace(/\u00a0/g, " ").trim();
  }

  function tableToRows(table) {
    const rows = [];
    for (const tr of table.querySelectorAll("tr")) {
      const row = [...tr.querySelectorAll("th,td")].map(td => clean(td.innerText));
      if (row.length > 0) rows.push(row);
    }
    return rows;
  }

  const payload = {
    exported_at: new Date().toISOString(),
    url: location.href,
    title: document.title,
    pathname: location.pathname,
    search: location.search,
    visible_text: document.body.innerText,
    tables: [...document.querySelectorAll("table")].map(tableToRows),
    links: [...document.querySelectorAll("a")].map(a => ({
      text: clean(a.innerText),
      href: a.href
    })).filter(x => x.text || x.href)
  };

  const safeName = location.pathname
    .replaceAll("/", "_")
    .replace(/[^a-zA-Z0-9_ -]/g, "")
    .replace(/^_+/, "") || "wq_page";

  const blob = new Blob([JSON.stringify(payload, null, 2)], {
    type: "application/json;charset=utf-8"
  });

  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `wq_export_${safeName}_${Date.now()}.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);

  console.log("Exported current visible page as JSON:", payload);
})();
