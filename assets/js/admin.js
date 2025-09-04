async function fetchPending(apiBase, path) {
    // No direct endpoint provided; query storage elsewhere or extend API:
    // For simplicity, we'll reuse GET approved and ask you to flip status
    // => Add a quick helper endpoint if you want true pending listing.
    alert("For full pending listing, create an admin-only endpoint or use Azure Storage Explorer. This console just sends approve/delete by id once you know it.");
}

async function moderate(apiBase, key, action, path, id) {
    const res = await fetch(`${apiBase}/comments/moderate?code=${encodeURIComponent(key)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, id, action })
    });
    const data = await res.json();
    alert(JSON.stringify(data, null, 2));
}

document.getElementById("load").addEventListener("click", () => {
    const apiBase = document.getElementById("apiBase").value.trim();
    const key = document.getElementById("fnKey").value.trim();
    const path = document.getElementById("path").value.trim();
    // You can paste a RowKey to approve/delete:
    const id = prompt("Enter Comment RowKey to approve/delete:");
    if (!id) return;
    const act = prompt('Type "approve" or "delete":');
    if (act !== "approve" && act !== "delete") return;
    moderate(apiBase, key, act, path, id);
});
