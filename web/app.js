const state = {
  jobs: [],
  meta: null,
  category: "all",
  region: "all",
  query: "",
  refreshing: false,
};

const els = {
  jobList: document.getElementById("job-list"),
  emptyState: document.getElementById("empty-state"),
  resultCount: document.getElementById("result-count"),
  jobCount: document.getElementById("job-count"),
  priorityCount: document.getElementById("priority-count"),
  lastUpdated: document.getElementById("last-updated"),
  countShenzhen: document.getElementById("count-shenzhen"),
  countGuangzhou: document.getElementById("count-guangzhou"),
  countHongkong: document.getElementById("count-hongkong"),
  countNew: document.getElementById("count-new"),
  priorityBadge: document.getElementById("priority-badge"),
  priorityList: document.getElementById("priority-list"),
  apiStatus: document.getElementById("api-status"),
  apiLatestEndpoint: document.getElementById("api-latest-endpoint"),
  apiJobsEndpoint: document.getElementById("api-jobs-endpoint"),
  apiMetaEndpoint: document.getElementById("api-meta-endpoint"),
  refreshButton: document.getElementById("refresh-button"),
  searchInput: document.getElementById("search-input"),
  template: document.getElementById("job-card-template"),
};

async function loadJobs() {
  const [jobsResponse, metaResponse] = await Promise.all([
    fetch("./data/latest.json", { cache: "no-store" }),
    fetch("./data/meta.json", { cache: "no-store" }).catch(() => null),
  ]);

  if (!jobsResponse.ok) {
    throw new Error(`Failed to load jobs: ${jobsResponse.status}`);
  }

  state.jobs = await jobsResponse.json();
  state.meta = metaResponse && metaResponse.ok ? await metaResponse.json() : null;
  renderSummary();
  renderPriority();
  renderApiInfo();
  renderJobs();
}

function renderSummary() {
  const jobs = state.jobs;
  els.jobCount.textContent = String(jobs.length);
  els.priorityCount.textContent = String(jobs.filter((job) => job.category === "高匹配春招").length);
  els.countShenzhen.textContent = String(jobs.filter((job) => job.region === "深圳").length);
  els.countGuangzhou.textContent = String(jobs.filter((job) => job.region === "广州").length);
  els.countHongkong.textContent = String(jobs.filter((job) => job.region === "香港").length);
  els.countNew.textContent = String(jobs.filter((job) => job.is_new).length);

  if (state.meta && state.meta.generated_at_display) {
    els.lastUpdated.textContent = formatDateTime(state.meta.generated_at_display || state.meta.generated_at);
  } else {
    const latestDate = jobs
      .map((job) => job.published_date)
      .filter(Boolean)
      .sort()
      .at(-1);
    els.lastUpdated.textContent = latestDate || "暂无";
  }
}

function renderPriority() {
  const priorityJobs = state.jobs.filter((job) => job.category === "高匹配春招").slice(0, 3);
  els.priorityBadge.textContent = `${priorityJobs.length} 条高匹配`;
  els.priorityList.innerHTML = "";

  if (priorityJobs.length === 0) {
    els.priorityList.innerHTML = "<p class=\"job-summary\">今天没有进入高匹配区的岗位。</p>";
    return;
  }

  priorityJobs.forEach((job) => {
    const item = document.createElement("article");
    item.className = "priority-item";
    item.innerHTML = `
      <h3>${escapeHtml(job.title)}</h3>
      <p>${escapeHtml(job.company)} · ${escapeHtml(job.region)} · ${escapeHtml(job.location || "地点待补充")}</p>
      <p>${escapeHtml((job.reasons || []).join("、") || "人工筛选")}</p>
      <p><a href="${job.url}" target="_blank" rel="noreferrer">查看原岗位</a></p>
    `;
    els.priorityList.appendChild(item);
  });
}

function renderApiInfo() {
  const baseUrl = `${window.location.origin}`;
  els.apiLatestEndpoint.textContent = `${baseUrl}/jobhunter-api/latest`;
  els.apiJobsEndpoint.textContent = `${baseUrl}/jobhunter-api/jobs?region=深圳&category=高匹配春招`;
  els.apiMetaEndpoint.textContent = `${baseUrl}/jobhunter-api/meta`;
  checkApiHealth();
}

async function checkApiHealth() {
  try {
    const response = await fetch("/jobhunter-api/health", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(String(response.status));
    }
    els.apiStatus.textContent = "API 在线";
    els.apiStatus.classList.add("ok");
    els.apiStatus.classList.remove("fail");
  } catch (error) {
    els.apiStatus.textContent = "API 未连通";
    els.apiStatus.classList.add("fail");
    els.apiStatus.classList.remove("ok");
  }
}

async function triggerRefresh() {
  if (state.refreshing) {
    return;
  }

  state.refreshing = true;
  els.refreshButton.disabled = true;
  els.refreshButton.textContent = "刷新中...";

  try {
    const response = await fetch("/jobhunter-api/refresh", {
      method: "POST",
    });
    if (!response.ok) {
      throw new Error(String(response.status));
    }
    await loadJobs();
  } catch (error) {
    console.error(error);
    alert("刷新失败，请稍后再试。");
  } finally {
    state.refreshing = false;
    els.refreshButton.disabled = false;
    els.refreshButton.textContent = "立即刷新";
  }
}

function getFilteredJobs() {
  return state.jobs.filter((job) => {
    if (state.category !== "all" && job.category !== state.category) {
      return false;
    }
    if (state.region !== "all" && job.region !== state.region) {
      return false;
    }
    if (!state.query) {
      return true;
    }
    const haystack = [
      job.title,
      job.company,
      job.location,
      job.summary,
      job.region,
      job.category,
      ...(job.tags || []),
    ]
      .join(" ")
      .toLowerCase();
    return haystack.includes(state.query);
  });
}

function renderJobs() {
  const jobs = getFilteredJobs();
  els.jobList.innerHTML = "";
  els.resultCount.textContent = `${jobs.length} 条`;
  els.emptyState.classList.toggle("hidden", jobs.length > 0);

  jobs.forEach((job) => {
    const node = els.template.content.firstElementChild.cloneNode(true);
    node.querySelector(".job-region").textContent = job.region;

    const categoryEl = node.querySelector(".job-category");
    categoryEl.textContent = job.category;
    if (job.category === "高匹配春招") {
      categoryEl.classList.add("priority");
    }

    node.querySelector(".job-title").textContent = job.title;
    node.querySelector(".job-company").textContent = job.company;
    node.querySelector(".job-meta").textContent = formatMeta(job);
    node.querySelector(".job-summary").textContent = job.summary || "暂无岗位摘要";
    node.querySelector(".job-reasons").textContent = `判断理由：${(job.reasons || []).join("、") || "人工筛选"}`;

    const link = node.querySelector(".job-link");
    link.href = job.url;

    const tagsEl = node.querySelector(".job-tags");
    const tags = [...(job.tags || [])];
    if (job.is_new) {
      tags.unshift("新发现");
    }
    tags.slice(0, 6).forEach((tag) => {
      const span = document.createElement("span");
      span.className = "job-tag";
      span.textContent = tag;
      tagsEl.appendChild(span);
    });

    els.jobList.appendChild(node);
  });
}

function formatMeta(job) {
  return [job.location, job.experience, job.salary, job.published_text]
    .filter(Boolean)
    .join(" | ");
}

function formatDateTime(value) {
  if (!value) {
    return "暂无";
  }
  if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(value)) {
    return value;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hour = String(date.getHours()).padStart(2, "0");
  const minute = String(date.getMinutes()).padStart(2, "0");
  const second = String(date.getSeconds()).padStart(2, "0");
  return `${year}-${month}-${day} ${hour}:${minute}:${second}`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function bindFilters() {
  document.querySelectorAll("[data-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      state.category = button.dataset.filter;
      document.querySelectorAll("[data-filter]").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      renderJobs();
    });
  });

  document.querySelectorAll("[data-region]").forEach((button) => {
    button.addEventListener("click", () => {
      state.region = button.dataset.region;
      document.querySelectorAll("[data-region]").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      renderJobs();
    });
  });

  els.searchInput.addEventListener("input", (event) => {
    state.query = event.target.value.trim().toLowerCase();
    renderJobs();
  });

  if (els.refreshButton) {
    els.refreshButton.addEventListener("click", () => {
      triggerRefresh();
    });
  }
}

async function boot() {
  bindFilters();
  try {
    await loadJobs();
  } catch (error) {
    els.emptyState.textContent = "数据加载失败。请先运行 job_digest.py 生成 web/data/latest.json。";
    els.emptyState.classList.remove("hidden");
    console.error(error);
  }
}

boot();
