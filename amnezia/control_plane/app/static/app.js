const responseBox = document.getElementById("response-box");
const clientsBody = document.getElementById("clients-body");

const clientIdInput = document.getElementById("client_id");
const addDaysInput = document.getElementById("add_days");
const metricProtocol = document.getElementById("metric-protocol");
const metricRx = document.getElementById("metric-rx");
const metricTx = document.getElementById("metric-tx");
const metricTotal = document.getElementById("metric-total");

let lineChart = null;
let userChart = null;

function setResponse(data) {
  responseBox.textContent = JSON.stringify(data, null, 2);
}

async function api(path, options = {}) {
  const { headers: optionHeaders, ...fetchRest } = options;
  const response = await fetch(path, {
    ...fetchRest,
    headers: {
      "Content-Type": "application/json",
      ...(optionHeaders || {}),
    },
  });

  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = { message: "No JSON response" };
  }

  if (!response.ok) {
    throw new Error(JSON.stringify(payload, null, 2));
  }
  return payload;
}

function formatBytes(bytes) {
  if (!bytes) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = Number(bytes);
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${size.toFixed(size < 10 && unitIndex > 0 ? 2 : 1)} ${units[unitIndex]}`;
}

function renderCharts(stats) {
  const labels = stats.series_24h.map((point) => point.ts.slice(11, 16));
  const rxData = stats.series_24h.map((point) => point.rx_bytes);
  const txData = stats.series_24h.map((point) => point.tx_bytes);
  const users = stats.per_user.slice(0, 10);
  const userLabels = users.map((item) => String(item.telegram_user_id));
  const userTotals = users.map((item) => item.total_bytes);

  if (lineChart) {
    lineChart.destroy();
  }
  if (userChart) {
    userChart.destroy();
  }

  lineChart = new Chart(document.getElementById("traffic-line-chart"), {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Inbound RX",
          data: rxData,
          borderColor: "#22c55e",
          backgroundColor: "rgba(34,197,94,0.25)",
        },
        {
          label: "Outbound TX",
          data: txData,
          borderColor: "#60a5fa",
          backgroundColor: "rgba(96,165,250,0.25)",
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: {
          ticks: {
            callback: (value) => formatBytes(value),
          },
        },
      },
      plugins: { legend: { labels: { color: "#e2e8f0" } } },
    },
  });

  userChart = new Chart(document.getElementById("traffic-user-chart"), {
    type: "bar",
    data: {
      labels: userLabels,
      datasets: [
        {
          label: "User traffic",
          data: userTotals,
          backgroundColor: "#3b82f6",
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: {
          ticks: {
            callback: (value) => formatBytes(value),
          },
        },
      },
      plugins: { legend: { labels: { color: "#e2e8f0" } } },
    },
  });
}

async function refreshStats() {
  try {
    const stats = await api("/v1/stats/traffic");
    metricProtocol.textContent = stats.protocol;
    metricRx.textContent = formatBytes(stats.totals.rx_bytes);
    metricTx.textContent = formatBytes(stats.totals.tx_bytes);
    metricTotal.textContent = formatBytes(stats.totals.total_bytes);
    renderCharts(stats);
  } catch (error) {
    setResponse({ error: String(error) });
  }
}

async function refreshList() {
  try {
    const clients = await api("/v1/clients");
    clientsBody.innerHTML = "";
    for (const c of clients) {
      const row = document.createElement("tr");
      row.innerHTML = `
        <td>${c.client_id}</td>
        <td>${c.telegram_user_id}</td>
        <td>${c.active ? "yes" : "no"}</td>
        <td>${c.expires_at}</td>
      `;
      row.addEventListener("click", () => {
        clientIdInput.value = c.client_id;
      });
      clientsBody.appendChild(row);
    }
  } catch (error) {
    setResponse({ error: String(error) });
  }
}

document.getElementById("create-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {
    telegram_user_id: Number(document.getElementById("telegram_user_id").value),
    plan_days: Number(document.getElementById("plan_days").value),
    remark: document.getElementById("remark").value,
  };
  try {
    const result = await api("/v1/clients", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    setResponse(result);
    clientIdInput.value = result.client_id;
    await refreshList();
    await refreshStats();
  } catch (error) {
    setResponse({ error: String(error) });
  }
});

document.getElementById("renew-btn").addEventListener("click", async () => {
  const clientId = clientIdInput.value.trim();
  if (!clientId) {
    setResponse({ error: "client_id required" });
    return;
  }
  try {
    const result = await api(`/v1/clients/${clientId}/renew`, {
      method: "POST",
      body: JSON.stringify({ add_days: Number(addDaysInput.value) }),
    });
    setResponse(result);
    await refreshList();
    await refreshStats();
  } catch (error) {
    setResponse({ error: String(error) });
  }
});

document.getElementById("revoke-btn").addEventListener("click", async () => {
  const clientId = clientIdInput.value.trim();
  if (!clientId) {
    setResponse({ error: "client_id required" });
    return;
  }
  try {
    const result = await api(`/v1/clients/${clientId}/revoke`, { method: "POST" });
    setResponse(result);
    await refreshList();
    await refreshStats();
  } catch (error) {
    setResponse({ error: String(error) });
  }
});

document.getElementById("config-btn").addEventListener("click", async () => {
  const clientId = clientIdInput.value.trim();
  if (!clientId) {
    setResponse({ error: "client_id required" });
    return;
  }
  try {
    const result = await api(`/v1/clients/${clientId}/config`);
    setResponse(result);
  } catch (error) {
    setResponse({ error: String(error) });
  }
});

document.getElementById("refresh-btn").addEventListener("click", async () => {
  await refreshList();
  await refreshStats();
});

document.getElementById("reboot-btn").addEventListener("click", async () => {
  const ok = window.confirm(
    "Schedule a full server reboot in 1 minute? SSH and VPN will drop until the host is back."
  );
  if (!ok) {
    return;
  }
  try {
    const result = await api("/v1/admin/reboot", {
      method: "POST",
      body: JSON.stringify({}),
      credentials: "include",
    });
    setResponse(result);
  } catch (error) {
    setResponse({ error: String(error) });
  }
});

refreshList();
refreshStats();
setInterval(refreshStats, 15000);
