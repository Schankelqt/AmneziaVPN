const responseBox = document.getElementById("response-box");
const clientsBody = document.getElementById("clients-body");

const clientIdInput = document.getElementById("client_id");
const addDaysInput = document.getElementById("add_days");
const qrCodeBox = document.getElementById("qrcode-box");
const metricProtocol = document.getElementById("metric-protocol");
const metricRx = document.getElementById("metric-rx");
const metricTx = document.getElementById("metric-tx");
const metricTotal = document.getElementById("metric-total");

let lineChart = null;
let userChart = null;

const chartDefaults = {
  responsive: true,
  maintainAspectRatio: false,
  layout: { padding: { top: 4, right: 4, bottom: 0, left: 4 } },
};

function setResponse(data) {
  responseBox.textContent = JSON.stringify(data, null, 2);
}

async function api(path, options = {}) {
  const { headers: optionHeaders, ...fetchRest } = options;
  const response = await fetch(path, {
    ...fetchRest,
    credentials: fetchRest.credentials ?? "same-origin",
    headers: {
      "Content-Type": "application/json",
      ...(optionHeaders || {}),
    },
  });

  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = { message: "Ответ не JSON" };
  }

  if (!response.ok) {
    throw new Error(JSON.stringify(payload, null, 2));
  }
  return payload;
}

function formatBytes(bytes) {
  if (!bytes) {
    return "0 Б";
  }
  const units = ["Б", "КБ", "МБ", "ГБ", "ТБ"];
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

  const lineCtx = document.getElementById("traffic-line-chart");
  const barCtx = document.getElementById("traffic-user-chart");

  lineChart = new Chart(lineCtx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Входящий RX",
          data: rxData,
          borderColor: "#22c55e",
          backgroundColor: "rgba(34,197,94,0.2)",
          fill: true,
          tension: 0.25,
          borderWidth: 2,
          pointRadius: 0,
          pointHoverRadius: 3,
        },
        {
          label: "Исходящий TX",
          data: txData,
          borderColor: "#60a5fa",
          backgroundColor: "rgba(96,165,250,0.15)",
          fill: true,
          tension: 0.25,
          borderWidth: 2,
          pointRadius: 0,
          pointHoverRadius: 3,
        },
      ],
    },
    options: {
      ...chartDefaults,
      interaction: { intersect: false, mode: "index" },
      scales: {
        x: {
          grid: { color: "rgba(148,163,184,0.12)" },
          ticks: { color: "#94a3b8", maxRotation: 0, font: { size: 10 } },
        },
        y: {
          grid: { color: "rgba(148,163,184,0.12)" },
          ticks: {
            color: "#94a3b8",
            font: { size: 10 },
            callback: (value) => formatBytes(value),
          },
        },
      },
      plugins: {
        legend: {
          labels: { color: "#e2e8f0", boxWidth: 12, font: { size: 11 } },
        },
      },
    },
  });

  userChart = new Chart(barCtx, {
    type: "bar",
    data: {
      labels: userLabels,
      datasets: [
        {
          label: "Трафик",
          data: userTotals,
          backgroundColor: "rgba(59,130,246,0.75)",
          borderRadius: 4,
          borderSkipped: false,
        },
      ],
    },
    options: {
      ...chartDefaults,
      scales: {
        x: {
          grid: { display: false },
          ticks: { color: "#94a3b8", font: { size: 10 } },
        },
        y: {
          grid: { color: "rgba(148,163,184,0.12)" },
          ticks: {
            color: "#94a3b8",
            font: { size: 10 },
            callback: (value) => formatBytes(value),
          },
        },
      },
      plugins: {
        legend: { display: false },
      },
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
        <td>${c.active ? "да" : "нет"}</td>
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
    setResponse({ error: "Укажите ID клиента" });
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
    setResponse({ error: "Укажите ID клиента" });
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
    setResponse({ error: "Укажите ID клиента" });
    return;
  }
  try {
    const result = await api(`/v1/clients/${clientId}/config`);
    setResponse(result);
  } catch (error) {
    setResponse({ error: String(error) });
  }
});

document.getElementById("qrcode-btn").addEventListener("click", async () => {
  const clientId = clientIdInput.value.trim();
  if (!clientId) {
    setResponse({ error: "Укажите ID клиента" });
    return;
  }
  try {
    const response = await fetch(`/v1/clients/${clientId}/qrcode.svg`, {
      credentials: "same-origin",
    });
    if (!response.ok) {
      let payload = { message: "Не удалось загрузить QR" };
      try {
        payload = await response.json();
      } catch {
        // Keep fallback payload
      }
      throw new Error(JSON.stringify(payload, null, 2));
    }
    const svg = await response.text();
    qrCodeBox.classList.remove("muted");
    qrCodeBox.innerHTML = svg;
  } catch (error) {
    qrCodeBox.classList.add("muted");
    qrCodeBox.textContent = "Не удалось загрузить QR.";
    setResponse({ error: String(error) });
  }
});

document.getElementById("refresh-btn").addEventListener("click", async () => {
  await refreshList();
  await refreshStats();
});

document.getElementById("reboot-btn").addEventListener("click", async () => {
  const ok = window.confirm(
    "Запланировать полную перезагрузку сервера через 1 минуту? SSH и VPN будут недоступны, пока машина не поднимется."
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
