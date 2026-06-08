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
  const gItem = e.target.closest(".js-gcal-item");
  if (gItem) {
    const li = e.target.closest("[data-item-id]");
    gItem.disabled = true;
    const old = gItem.textContent;
    gItem.textContent = "Adding…";
    postJSON(`/item/${li.dataset.itemId}/gcal`).then((r) => {
      gItem.textContent = r.ok ? "✓ Added to Google Calendar" : old;
      gItem.disabled = !r.ok;
      if (!r.ok) alert(r.error || "Could not add to Google Calendar");
    });
    return;
  }
  const gProj = e.target.closest(".js-gcal-project");
  if (gProj) {
    gProj.disabled = true;
    const old = gProj.textContent;
    gProj.textContent = "Syncing…";
    postJSON(`/project/${gProj.dataset.projectId}/gcal`).then((r) => {
      gProj.disabled = false;
      gProj.textContent = old;
      alert(r.ok ? `Added ${r.added} task(s) to your Google Calendar.`
                 : (r.error || "Could not sync to Google Calendar"));
    });
    return;
  }
  const delProj = e.target.closest(".js-delete-project");
  if (delProj) {
    if (confirm("Delete this entire project and all its tasks? This cannot be undone.")) {
      postJSON(`/project/${delProj.dataset.projectId}/delete`).then(() => {
        window.location = "/projects";
      });
    }
    return;
  }
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
  if (e.target.classList.contains("js-delete-everyday")) {
    const li = e.target.closest("[data-everyday-id]");
    if (confirm("Delete this everyday item?")) {
      postJSON(`/everyday/${li.dataset.everydayId}/delete`).then(() =>
        window.location.reload()
      );
    }
  }
  if (e.target.classList.contains("js-add-everyday")) {
    const projectId = e.target.dataset.projectId;
    const title = prompt("New everyday item?");
    if (title) {
      postJSON(`/project/${projectId}/everyday`, { title }).then(() =>
        window.location.reload()
      );
    }
  }
});
