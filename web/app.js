const state = {
  jobs: [],
  meta: null,
  resumeMeta: null,
  apiAvailable: true,
  refreshing: false,
  uploadingResume: false,
  filters: {
    深圳: { query: "", salary: "all", companySize: "preferred_large" },
    香港: { query: "", salary: "all", companySize: "all" },
  },
};

const els = {
  lastUpdated: document.getElementById("last-updated"),
  jobCount: document.getElementById("job-count"),
  recommendedCount: document.getElementById("recommended-count"),
  countShenzhen: document.getElementById("count-shenzhen"),
  countShenzhenRecommended: document.getElementById("count-shenzhen-recommended"),
  countHongkong: document.getElementById("count-hongkong"),
  countHongkongRecommended: document.getElementById("count-hongkong-recommended"),
  refreshButton: document.getElementById("refresh-button"),
  resumeFile: document.getElementById("resume-file"),
  resumeUploadButton: document.getElementById("resume-upload-button"),
  resumeStatus: document.getElementById("resume-status"),
  template: document.getElementById("job-card-template"),
  metrics: {
    深圳: {
      total: document.getElementById("metric-shenzhen-total"),
      recommended: document.getElementById("metric-shenzhen-recommended"),
      recommendedCount: document.getElementById("recommended-shenzhen-count"),
      allCount: document.getElementById("all-shenzhen-count"),
      recommendedList: document.getElementById("recommended-shenzhen"),
      jobsList: document.getElementById("jobs-shenzhen"),
      empty: document.getElementById("empty-shenzhen"),
      search: document.getElementById("search-shenzhen"),
      salary: document.getElementById("salary-shenzhen"),
      companySize: document.getElementById("size-shenzhen"),
    },
    香港: {
      total: document.getElementById("metric-hongkong-total"),
      recommended: document.getElementById("metric-hongkong-recommended"),
      recommendedCount: document.getElementById("recommended-hongkong-count"),
      allCount: document.getElementById("all-hongkong-count"),
      recommendedList: document.getElementById("recommended-hongkong"),
      jobsList: document.getElementById("jobs-hongkong"),
      empty: document.getElementById("empty-hongkong"),
      search: document.getElementById("search-hongkong"),
      salary: document.getElementById("salary-hongkong"),
      companySize: document.getElementById("size-hongkong"),
    },
  },
};

async function loadData() {
  try {
    const [latestResponse, metaResponse, resumeResponse] = await Promise.all([
      fetch("/jobhunter-api/latest", { cache: "no-store" }),
      fetch("/jobhunter-api/meta", { cache: "no-store" }),
      fetch("/jobhunter-api/resume/meta", { cache: "no-store" }),
    ]);
    if (!latestResponse.ok || !metaResponse.ok) {
      throw new Error("api failed");
    }
    const latestPayload = await latestResponse.json();
    state.jobs = latestPayload.items || [];
    state.meta = await metaResponse.json();
    state.resumeMeta = resumeResponse.ok ? await resumeResponse.json() : null;
    state.apiAvailable = true;
  } catch (error) {
    const [jobsResponse, metaResponse] = await Promise.all([
      fetch("./data/latest.json", { cache: "no-store" }),
      fetch("./data/meta.json", { cache: "no-store" }).catch(() => null),
    ]);
    if (!jobsResponse.ok) {
      throw new Error(`Failed to load jobs: ${jobsResponse.status}`);
    }
    state.jobs = await jobsResponse.json();
    state.meta = metaResponse && metaResponse.ok ? await metaResponse.json() : null;
    state.resumeMeta = null;
    state.apiAvailable = false;
  }
  renderPage();
}

function renderPage() {
  renderSummary();
  renderResumeStatus();
  renderRegion("深圳");
  renderRegion("香港");
}

function renderSummary() {
  const shenzhenJobs = state.jobs.filter((job) => job.region === "深圳");
  const hongkongJobs = state.jobs.filter((job) => job.region === "香港");
  const recommendedJobs = state.jobs.filter((job) => job.recommended);

  els.jobCount.textContent = String(state.jobs.length);
  els.recommendedCount.textContent = String(recommendedJobs.length);
  els.countShenzhen.textContent = String(shenzhenJobs.length);
  els.countShenzhenRecommended.textContent = String(shenzhenJobs.filter((job) => job.recommended).length);
  els.countHongkong.textContent = String(hongkongJobs.length);
  els.countHongkongRecommended.textContent = String(hongkongJobs.filter((job) => job.recommended).length);

  if (state.meta && state.meta.generated_at_display) {
    els.lastUpdated.textContent = formatDateTime(state.meta.generated_at_display || state.meta.generated_at);
  } else {
    els.lastUpdated.textContent = "暂无";
  }
}

function renderResumeStatus() {
  if (!state.apiAvailable) {
    els.resumeStatus.textContent = "当前是静态数据模式，简历上传只在线上 API 可用时生效。";
    return;
  }
  if (state.resumeMeta && state.resumeMeta.has_resume) {
    const roles = (state.resumeMeta.target_roles || []).join(" / ") || "未提取方向";
    els.resumeStatus.textContent = `已上传 ${state.resumeMeta.filename}，最近更新 ${formatDateTime(state.resumeMeta.updated_at)}，匹配方向：${roles}`;
    return;
  }
  els.resumeStatus.textContent = "尚未上传简历";
}

function renderRegion(region) {
  const metrics = els.metrics[region];
  const jobs = getFilteredJobs(region);
  const recommended = [...jobs]
    .filter((job) => job.recommended || (job.match_score || 0) > 0)
    .sort((a, b) => {
      const scoreDiff = Number(b.match_score || 0) - Number(a.match_score || 0);
      if (scoreDiff !== 0) {
        return scoreDiff;
      }
      return Number(b.base_score || 0) - Number(a.base_score || 0);
    })
    .slice(0, 6);

  metrics.total.textContent = `${jobs.length} 个岗位`;
  metrics.recommended.textContent = `${recommended.length} 个优先推荐`;
  metrics.recommendedCount.textContent = `${recommended.length} 条`;
  metrics.allCount.textContent = `${jobs.length} 条`;
  metrics.recommendedList.innerHTML = "";
  metrics.jobsList.innerHTML = "";
  metrics.empty.classList.toggle("hidden", jobs.length > 0);

  if (recommended.length === 0) {
    const emptyNode = document.createElement("div");
    emptyNode.className = "empty-inline";
    emptyNode.textContent = state.resumeMeta && state.resumeMeta.has_resume ? "当前筛选下还没有明显更高匹配的岗位。" : "上传简历后，这里会优先显示更匹配的岗位。";
    metrics.recommendedList.appendChild(emptyNode);
  } else {
    recommended.forEach((job) => {
      metrics.recommendedList.appendChild(createJobCard(job, true));
    });
  }

  jobs.forEach((job) => {
    metrics.jobsList.appendChild(createJobCard(job, false));
  });
}

function getFilteredJobs(region) {
  const filter = state.filters[region];
  const minSalary = salaryThreshold(filter.salary);

  return state.jobs.filter((job) => {
    if (job.region !== region) {
      return false;
    }
    if (!companySizeMatches(job, filter.companySize, region)) {
      return false;
    }
    if (minSalary !== null) {
      const salaryFloor = Math.max(Number(job.salary_min_monthly || 0), Number(job.salary_max_monthly || 0));
      if (!salaryFloor || salaryFloor < minSalary) {
        return false;
      }
    }
    if (!filter.query) {
      return true;
    }
    const haystack = [
      job.title,
      job.company,
      job.location,
      job.summary,
      job.source_platform,
      ...(job.tags || []),
      ...(job.match_reasons || []),
    ]
      .join(" ")
      .toLowerCase();
    return haystack.includes(filter.query);
  });
}

function createJobCard(job, highlight) {
  const node = els.template.content.firstElementChild.cloneNode(true);
  node.querySelector(".job-source").textContent = job.source_platform || job.source_name;
  node.querySelector(".job-company-size").textContent = humanCompanySize(job.company_size_bucket);
  node.querySelector(".job-title").textContent = job.title;
  node.querySelector(".job-company").textContent = job.company;
  node.querySelector(".job-meta").textContent = formatMeta(job);
  node.querySelector(".job-summary").textContent = job.summary || "暂无岗位摘要";

  const reasons = node.querySelector(".job-reasons");
  const reasonText = highlight
    ? `推荐理由：${(job.match_reasons || []).join("、") || (job.reasons || []).join("、") || "基础筛选结果"}`
    : `筛选理由：${(job.reasons || []).join("、") || "基础筛选结果"}`;
  reasons.textContent = reasonText;

  const link = node.querySelector(".job-link");
  link.href = job.url;

  const tags = node.querySelector(".job-tags");
  const tagValues = [];
  if (job.recommended) {
    tagValues.push("优先推荐");
  }
  if (job.is_new) {
    tagValues.push("新发现");
  }
  if (job.match_score) {
    tagValues.push(`匹配分 ${job.match_score}`);
  }
  if (job.salary_currency) {
    tagValues.push(job.salary_currency);
  }
  (job.tags || []).slice(0, 4).forEach((tag) => tagValues.push(tag));
  tagValues.forEach((tag) => {
    const span = document.createElement("span");
    span.className = "job-tag";
    span.textContent = tag;
    tags.appendChild(span);
  });

  return node;
}

function formatMeta(job) {
  return [
    job.location,
    job.experience,
    job.salary,
    humanCompanySize(job.company_size_bucket),
    job.published_text,
  ]
    .filter(Boolean)
    .join(" | ");
}

function humanCompanySize(bucket) {
  return {
    "10000_plus": "10000+人",
    "1000_9999": "1000-9999人",
    "100_999": "100-999人",
    "1_99": "1-99人",
    unknown: "规模未知",
  }[bucket || "unknown"] || "规模未知";
}

function companySizeMatches(job, filter, region) {
  const bucket = job.company_size_bucket || "unknown";
  if (!filter || filter === "all") {
    return true;
  }
  if (filter === "preferred_large") {
    if (region !== "深圳") {
      return true;
    }
    return bucket === "10000_plus" || bucket === "unknown";
  }
  return bucket === filter;
}

function salaryThreshold(value) {
  return {
    "10k_plus": 10000,
    "15k_plus": 15000,
    "20k_plus": 20000,
  }[value] ?? null;
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

async function triggerRefresh() {
  if (!state.apiAvailable || state.refreshing) {
    return;
  }
  state.refreshing = true;
  els.refreshButton.disabled = true;
  els.refreshButton.textContent = "刷新中...";
  try {
    const response = await fetch("/jobhunter-api/refresh", { method: "POST" });
    if (!response.ok) {
      throw new Error(String(response.status));
    }
    await loadData();
  } catch (error) {
    console.error(error);
    alert("刷新失败，请稍后再试。");
  } finally {
    state.refreshing = false;
    els.refreshButton.disabled = false;
    els.refreshButton.textContent = "立即刷新";
  }
}

async function uploadResume() {
  if (!state.apiAvailable || state.uploadingResume) {
    return;
  }
  const file = els.resumeFile.files && els.resumeFile.files[0];
  if (!file) {
    alert("先选择简历文件。");
    return;
  }
  state.uploadingResume = true;
  els.resumeUploadButton.disabled = true;
  els.resumeUploadButton.textContent = "上传中...";
  try {
    const contentBase64 = await readFileAsBase64(file);
    const response = await fetch("/jobhunter-api/resume", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        filename: file.name,
        content_base64: contentBase64,
      }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || String(response.status));
    }
    state.resumeMeta = payload.resume;
    await loadData();
  } catch (error) {
    console.error(error);
    alert(`简历上传失败：${error.message}`);
  } finally {
    state.uploadingResume = false;
    els.resumeUploadButton.disabled = false;
    els.resumeUploadButton.textContent = "上传简历";
  }
}

function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("文件读取失败"));
    reader.onload = () => resolve(String(reader.result || ""));
    reader.readAsDataURL(file);
  });
}

function bindControls() {
  ["深圳", "香港"].forEach((region) => {
    const metrics = els.metrics[region];
    metrics.search.addEventListener("input", (event) => {
      state.filters[region].query = event.target.value.trim().toLowerCase();
      renderRegion(region);
    });
    metrics.salary.addEventListener("change", (event) => {
      state.filters[region].salary = event.target.value;
      renderRegion(region);
    });
    metrics.companySize.addEventListener("change", (event) => {
      state.filters[region].companySize = event.target.value;
      renderRegion(region);
    });
  });

  if (els.refreshButton) {
    els.refreshButton.addEventListener("click", () => {
      triggerRefresh();
    });
  }
  if (els.resumeUploadButton) {
    els.resumeUploadButton.addEventListener("click", () => {
      uploadResume();
    });
  }
}

async function boot() {
  bindControls();
  try {
    await loadData();
  } catch (error) {
    console.error(error);
    els.lastUpdated.textContent = "数据加载失败";
  }
}

boot();
