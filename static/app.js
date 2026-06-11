// Wires project-page interactions to the JSON endpoints from app.py.
async function postJSON(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  return r.json();
}

const uploadForm = document.querySelector("[data-upload-form]");
if (uploadForm) {
  uploadForm.addEventListener("submit", () => {
    const loading = document.querySelector("[data-upload-loading]");
    const submit = document.querySelector("[data-upload-submit]");
    if (submit) {
      submit.disabled = true;
      submit.classList.add("opacity-60", "cursor-wait");
      submit.textContent = "Generating...";
    }
    if (loading) {
      loading.classList.remove("hidden");
      loading.classList.add("flex");
    }
  });
}

document.addEventListener("change", (e) => {
  if (e.target.classList.contains("js-status")) {
    const li = e.target.closest("[data-item-id]");
    const status = e.target.checked ? "done" : "todo";
    postJSON(`/item/${li.dataset.itemId}/status`, { status }).then(() =>
      window.location.reload()
    );
  }
  if (e.target.classList.contains("js-everyday-status")) {
    const li = e.target.closest("[data-everyday-id]");
    const status = e.target.checked ? "done" : "todo";
    postJSON(`/everyday/${li.dataset.everydayId}/status`, { status }).then(() =>
      window.location.reload()
    );
  }
  if (e.target.classList.contains("js-everyday-day")) {
    const cb = e.target;
    // Persist the per-day completion; no reload so the grid stays put.
    postJSON(`/everyday/${cb.dataset.everydayId}/day`, {
      day: cb.dataset.day,
      done: cb.checked,
    });
  }
});

document.addEventListener("click", (e) => {
  const delProj = e.target.closest(".js-delete-project");
  if (delProj) {
    if (confirm("Delete this entire project and all its tasks? This cannot be undone.")) {
      postJSON(`/project/${delProj.dataset.projectId}/delete`).then(() => {
        window.location = "/projects";
      });
    }
    return;
  }
  // closest() (not e.target.classList) so clicks on the SVGs inside these
  // buttons still resolve to the button.
  const del = e.target.closest(".js-delete");
  if (del) {
    const li = del.closest("[data-item-id]");
    if (confirm("Delete this item?")) {
      postJSON(`/item/${li.dataset.itemId}/delete`).then(() =>
        window.location.reload()
      );
    }
    return;
  }
  const addItem = e.target.closest(".js-add-item");
  if (addItem) {
    const title = prompt("New item title?");
    if (title) {
      postJSON(`/phase/${addItem.dataset.phaseId}/item`, { title }).then(() =>
        window.location.reload()
      );
    }
    return;
  }
  const addPhase = e.target.closest(".js-add-phase");
  if (addPhase) {
    const name = prompt("New phase name?");
    if (name) {
      postJSON(`/project/${addPhase.dataset.projectId}/phase`, { name }).then(
        () => window.location.reload()
      );
    }
    return;
  }
  const delEveryday = e.target.closest(".js-delete-everyday");
  if (delEveryday) {
    const li = delEveryday.closest("[data-everyday-id]");
    if (confirm("Delete this everyday item?")) {
      postJSON(`/everyday/${li.dataset.everydayId}/delete`).then(() =>
        window.location.reload()
      );
    }
    return;
  }
  const addEveryday = e.target.closest(".js-add-everyday");
  if (addEveryday) {
    const title = prompt("New everyday item?");
    if (title) {
      postJSON(`/project/${addEveryday.dataset.projectId}/everyday`, {
        title,
      }).then(() => window.location.reload());
    }
  }
});
