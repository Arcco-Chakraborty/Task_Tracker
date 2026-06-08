// Wires project-page interactions to the JSON endpoints from app.py.
async function postJSON(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  return r.json();
}

document.addEventListener("change", (e) => {
  if (e.target.classList.contains("js-status")) {
    const li = e.target.closest("[data-item-id]");
    const status = e.target.checked ? "done" : "todo";
    postJSON(`/item/${li.dataset.itemId}/status`, { status }).then(() =>
      window.location.reload()
    );
  }
});

document.addEventListener("click", (e) => {
  if (e.target.classList.contains("js-delete")) {
    const li = e.target.closest("[data-item-id]");
    if (confirm("Delete this item?")) {
      postJSON(`/item/${li.dataset.itemId}/delete`).then(() =>
        window.location.reload()
      );
    }
  }
  if (e.target.classList.contains("js-add-item")) {
    const phaseId = e.target.dataset.phaseId;
    const title = prompt("New item title?");
    if (title) {
      postJSON(`/phase/${phaseId}/item`, { title }).then(() =>
        window.location.reload()
      );
    }
  }
  if (e.target.classList.contains("js-add-phase")) {
    const projectId = e.target.dataset.projectId;
    const name = prompt("New phase name?");
    if (name) {
      postJSON(`/project/${projectId}/phase`, { name }).then(() =>
        window.location.reload()
      );
    }
  }
});
