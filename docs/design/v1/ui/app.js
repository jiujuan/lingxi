(function () {
  const pageMeta = {
    dashboard: ["首页 Dashboard", "今日客服运行、AI 命中、知识增长与风险摘要"],
    knowledge: ["知识中心", "知识接入、解析、审核、发布、FAQ 和 Chunk 治理"],
    chat: ["AI 客服", "RAG 回答、引用来源、反馈和转人工"],
    tickets: ["工单中心", "人工接管、优先级、通知和处理记录"],
    operations: ["知识运营", "命中率、未命中、热门知识和知识健康"],
    "ai-config": ["AI 配置", "模型供应商、Prompt、RAG 参数和标准测试集"],
    access: ["用户权限", "用户、部门、角色、RBAC 权限和审计"],
    settings: ["系统设置", "企业信息、对象存储、API、Webhook、渠道和 Widget"],
  };

  const modalContent = {
    webhook: {
      title: "Webhook 事件",
      body:
        "<p>已启用事件：knowledge.published、ai.answer.generated、ticket.created、ticket.closed。</p><p>签名方式：HMAC-SHA256。失败投递将进入指数退避重试。</p>",
      confirm: "保存",
    },
    version: {
      title: "知识版本",
      body:
        "<p>当前版本 V3，上一版本 V2 保留引用快照。发布新版本会触发重新 Chunk 和 Embedding。</p>",
      confirm: "知道了",
    },
    review: {
      title: "提交审核",
      body:
        "<p>该知识属于退款高风险分类，提交后将进入管理员审核队列。审核通过后才会发布到客户侧检索范围。</p>",
      confirm: "提交",
    },
    faq: {
      title: "编辑 FAQ",
      body:
        '<label>问题<input type="text" value="升级套餐后多久生效？"></label><label>答案<input type="text" value="支付成功后 5 分钟内生效。"></label>',
      confirm: "保存",
    },
    ticket: {
      title: "新建工单",
      body:
        '<label>标题<input type="text" value="客户咨询退款"></label><label>优先级<select><option>MEDIUM</option><option>HIGH</option><option>URGENT</option></select></label>',
      confirm: "创建",
    },
    user: {
      title: "邀请用户",
      body:
        '<label>邮箱<input type="email" value="new.user@example.com"></label><label>角色<select><option>客服</option><option>知识管理员</option><option>管理员</option></select></label>',
      confirm: "发送邀请",
    },
  };

  const appShell = document.querySelector(".app-shell");
  const pageTitle = document.getElementById("pageTitle");
  const pageSubtitle = document.getElementById("pageSubtitle");
  const modal = document.getElementById("modal");
  const modalTitle = document.getElementById("modalTitle");
  const modalBody = document.getElementById("modalBody");
  const modalConfirm = document.getElementById("modalConfirm");
  const modalCancel = document.getElementById("modalCancel");
  const modalClose = document.getElementById("modalClose");
  const toastRegion = document.getElementById("toastRegion");

  function showToast(message) {
    const toast = document.createElement("div");
    toast.className = "toast";
    toast.textContent = message;
    toastRegion.appendChild(toast);
    window.setTimeout(() => {
      toast.remove();
    }, 2800);
  }

  function setView(viewName) {
    document.querySelectorAll(".view").forEach((view) => {
      view.classList.toggle("is-active", view.id === `view-${viewName}`);
    });
    document.querySelectorAll(".nav-item").forEach((item) => {
      item.classList.toggle("is-active", item.dataset.view === viewName);
    });
    const meta = pageMeta[viewName];
    if (meta) {
      pageTitle.textContent = meta[0];
      pageSubtitle.textContent = meta[1];
    }
    if (window.innerWidth <= 820) {
      appShell.dataset.sidebar = "closed";
    }
  }

  function syncSidebarForViewport() {
    if (window.innerWidth <= 820) {
      appShell.dataset.sidebar = "closed";
    } else if (!appShell.dataset.sidebar) {
      appShell.dataset.sidebar = "open";
    }
  }

  function setKnowledgeTab(tabName) {
    document.querySelectorAll("[data-knowledge-tab]").forEach((button) => {
      if (button.closest(".tabbar")) {
        button.classList.toggle("is-active", button.dataset.knowledgeTab === tabName);
      }
    });
    document.querySelectorAll(".knowledge-tab").forEach((tab) => {
      tab.classList.toggle("is-active", tab.id === `knowledge-${tabName}`);
    });
  }

  function openModal(type) {
    const content = modalContent[type] || {
      title: "操作确认",
      body: "<p>确认执行当前操作。</p>",
      confirm: "确认",
    };
    modalTitle.textContent = content.title;
    modalBody.innerHTML = content.body;
    modalConfirm.textContent = content.confirm;
    modal.classList.add("is-open");
    modal.setAttribute("aria-hidden", "false");
    modalClose.focus();
  }

  function closeModal() {
    modal.classList.remove("is-open");
    modal.setAttribute("aria-hidden", "true");
  }

  function filterKnowledgeRows() {
    const query = document.getElementById("knowledgeSearch").value.trim();
    const category = document.getElementById("knowledgeCategory").value;
    const status = document.getElementById("knowledgeStatus").value;

    document.querySelectorAll("#knowledgeRows tr").forEach((row) => {
      const text = row.textContent || "";
      const categoryMatch = category === "all" || row.dataset.category === category;
      const statusMatch = status === "all" || row.dataset.status === status;
      const queryMatch = !query || text.includes(query);
      row.classList.toggle("is-hidden-row", !(categoryMatch && statusMatch && queryMatch));
    });
  }

  function simulateUpload() {
    const progress = document.getElementById("uploadProgress");
    const log = document.getElementById("uploadLog");
    const steps = Array.from(document.querySelectorAll(".pipeline-step"));
    const messages = [
      "object_key: tenant/t_001/imports/job_882/refund-sop.pdf",
      "MinerUParserAdapter: parsing PDF pages and tables",
      "ParsedDocument normalized: 128 blocks, 4 tables, 6 images",
      "ChunkService: generated 42 semantic chunks",
      "EmbeddingProvider: indexed vectors into pgvector",
      "ReviewService: high-risk refund policy routed to admin review",
    ];
    let current = 0;
    progress.style.width = "0%";
    steps.forEach((step, index) => {
      step.classList.toggle("is-done", index === 0);
      step.classList.remove("is-active");
    });
    log.textContent = "Import job created.\n";

    const timer = window.setInterval(() => {
      current += 1;
      progress.style.width = `${Math.min(current * 18, 100)}%`;
      if (messages[current - 1]) {
        log.textContent += `${messages[current - 1]}\n`;
      }
      if (steps[current]) {
        steps[current].classList.add("is-active");
      }
      if (steps[current - 1]) {
        steps[current - 1].classList.remove("is-active");
        steps[current - 1].classList.add("is-done");
      }
      if (current >= 6) {
        window.clearInterval(timer);
        steps.forEach((step) => step.classList.add("is-done"));
        showToast("上传解析完成，已进入审核队列");
      }
    }, 520);
  }

  function addMessage(kind, text) {
    const messages = document.getElementById("messages");
    const article = document.createElement("article");
    article.className = `message ${kind}`;
    const paragraph = document.createElement("p");
    paragraph.textContent = text;
    article.appendChild(paragraph);
    messages.appendChild(article);
    messages.scrollTop = messages.scrollHeight;
    return article;
  }

  function generateAiAnswer(question) {
    const answer = addMessage("ai", "");
    const paragraph = answer.querySelector("p");
    const text =
      "已开票订单仍可进入退款流程，但必须先完成发票红冲并由财务审核。客服需要确认订单号、付款流水和企业主体，不能直接承诺即时退款。";
    let index = 0;
    const timer = window.setInterval(() => {
      index += 3;
      paragraph.textContent = text.slice(0, index);
      if (index >= text.length) {
        window.clearInterval(timer);
        const citations = document.createElement("div");
        citations.className = "citations";
        citations.innerHTML =
          "<button type=\"button\">退款流程 SOP V3 · PDF 第 4 页</button><button type=\"button\">Chunk 13 · score 0.88</button>";
        const actions = document.createElement("div");
        actions.className = "message-actions";
        actions.innerHTML =
          "<button type=\"button\" data-action=\"copy-answer\">复制</button><button type=\"button\" data-action=\"regenerate\">重新回答</button><button type=\"button\" data-action=\"positive\">赞</button><button type=\"button\" data-action=\"negative\">踩</button><button type=\"button\" data-action=\"handoff\">转人工</button>";
        answer.append(citations, actions);
        showToast(`已基于知识库回答：${question}`);
      }
    }, 28);
  }

  function refreshChart() {
    document.querySelectorAll(".chart-row i").forEach((bar) => {
      const ai = 58 + Math.round(Math.random() * 32);
      const human = 12 + Math.round(Math.random() * 16);
      const ticket = 14 + Math.round(Math.random() * 22);
      bar.style.setProperty("--a", `${ai}%`);
      bar.style.setProperty("--b", `${human}%`);
      bar.style.setProperty("--c", `${ticket}%`);
    });
    showToast("趋势图已刷新");
  }

  function updateSliderLabels() {
    const topK = document.getElementById("topK");
    const rerank = document.getElementById("rerankTopK");
    const temperature = document.getElementById("temperature");
    const threshold = document.getElementById("threshold");
    document.getElementById("topKValue").textContent = topK.value;
    document.getElementById("rerankValue").textContent = rerank.value;
    document.getElementById("temperatureValue").textContent = (Number(temperature.value) / 100).toFixed(2);
    document.getElementById("thresholdValue").textContent = (Number(threshold.value) / 100).toFixed(2);
  }

  function runEvaluation() {
    const status = document.getElementById("evalStatus");
    status.textContent = "运行中";
    status.className = "pill warning";
    window.setTimeout(() => {
      document.getElementById("evalCitation").textContent = "83%";
      document.getElementById("evalFaith").textContent = "88%";
      document.getElementById("evalRefusal").textContent = "92%";
      document.getElementById("evalLatency").textContent = "1.7s";
      status.textContent = "通过";
      status.className = "pill success";
      showToast("标准测试集评估完成");
    }, 900);
  }

  function handleAction(action, target) {
    switch (action) {
      case "open-modal":
        openModal(target.dataset.modal);
        break;
      case "refresh-chart":
        refreshChart();
        break;
      case "draft-faq":
        showToast("已生成 FAQ 草稿，进入知识审核队列");
        setView("knowledge");
        setKnowledgeTab("faq");
        break;
      case "retry-import":
        showToast("已重新提交 Embedding 任务");
        break;
      case "approve-faq":
        target.closest(".faq-item").querySelector("span").textContent = "财务 · 已发布";
        showToast("FAQ 已发布并进入检索索引");
        break;
      case "approve-review":
        target.closest(".review-card").querySelector(".pill").textContent = "已发布";
        target.closest(".review-card").querySelector(".pill").className = "pill success";
        showToast("审核通过，知识已发布");
        break;
      case "reject-review":
        target.closest(".review-card").querySelector(".pill").textContent = "已驳回";
        target.closest(".review-card").querySelector(".pill").className = "pill danger";
        showToast("已驳回，需补充原因后重新提交");
        break;
      case "mark-reindex":
        showToast("Chunk 已标记为 REINDEX_REQUIRED");
        break;
      case "copy-answer":
        showToast("回答已复制");
        break;
      case "regenerate":
        generateAiAnswer("重新回答");
        break;
      case "positive":
        showToast("已记录正向反馈");
        break;
      case "negative":
        showToast("已记录点踩原因：答案不完整");
        break;
      case "handoff":
        setView("tickets");
        showToast("会话已转为紧急工单");
        break;
      case "close-ticket":
        target.closest(".ticket-detail").querySelector("p").textContent = "工单已关闭，处理记录已沉淀为 FAQ 候选。";
        showToast("工单已关闭");
        break;
      case "assign-ticket":
        showToast("已转派给李主管，并发送企业微信通知");
        break;
      case "run-eval":
        runEvaluation();
        break;
      case "reset-rag":
        document.getElementById("topK").value = 20;
        document.getElementById("rerankTopK").value = 5;
        document.getElementById("temperature").value = 20;
        document.getElementById("threshold").value = 68;
        updateSliderLabels();
        showToast("RAG 参数已恢复默认值");
        break;
      case "save-permissions":
        showToast("权限矩阵已保存，后端 RBAC 将在新请求生效");
        break;
      case "save-settings":
        showToast("系统设置已保存");
        break;
      case "test-channels":
        showToast("企微、飞书、钉钉通知测试已发送");
        break;
      default:
        showToast("操作已触发");
    }
  }

  document.querySelectorAll(".nav-item").forEach((item) => {
    item.addEventListener("click", () => setView(item.dataset.view));
  });

  document.querySelectorAll("[data-view-jump]").forEach((item) => {
    item.addEventListener("click", () => {
      setView(item.dataset.viewJump);
      if (item.dataset.knowledgeTab) {
        setKnowledgeTab(item.dataset.knowledgeTab);
      }
    });
  });

  document.querySelectorAll("[data-knowledge-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      setView("knowledge");
      setKnowledgeTab(button.dataset.knowledgeTab);
    });
  });

  document.addEventListener("click", (event) => {
    const target = event.target.closest("[data-action]");
    if (target) {
      handleAction(target.dataset.action, target);
    }
  });

  document.getElementById("sidebarToggle").addEventListener("click", () => {
    appShell.dataset.sidebar = appShell.dataset.sidebar === "open" ? "closed" : "open";
  });

  document.getElementById("startUpload").addEventListener("click", simulateUpload);
  document.getElementById("dropZone").addEventListener("dblclick", simulateUpload);

  ["knowledgeSearch", "knowledgeCategory", "knowledgeStatus"].forEach((id) => {
    document.getElementById(id).addEventListener("input", filterKnowledgeRows);
  });

  document.getElementById("chatForm").addEventListener("submit", (event) => {
    event.preventDefault();
    const input = document.getElementById("chatInput");
    const question = input.value.trim();
    if (!question) return;
    addMessage("customer", question);
    input.value = "";
    generateAiAnswer(question);
  });

  document.getElementById("resetChat").addEventListener("click", () => {
    document.getElementById("messages").innerHTML = "";
    showToast("已创建新会话");
  });

  ["topK", "rerankTopK", "temperature", "threshold"].forEach((id) => {
    document.getElementById(id).addEventListener("input", updateSliderLabels);
  });

  document.getElementById("storageAdapter").addEventListener("change", (event) => {
    document.getElementById("uploadMode").textContent = event.target.value;
    showToast(`对象存储切换为 ${event.target.value}`);
  });

  document.getElementById("widgetBubble").addEventListener("click", () => {
    document.getElementById("widgetCard").classList.toggle("is-hidden");
  });

  [modalCancel, modalClose].forEach((button) => {
    button.addEventListener("click", closeModal);
  });

  modalConfirm.addEventListener("click", () => {
    showToast(`${modalTitle.textContent} 已确认`);
    closeModal();
  });

  modal.addEventListener("click", (event) => {
    if (event.target === modal) {
      closeModal();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && modal.classList.contains("is-open")) {
      closeModal();
    }
  });

  window.addEventListener("resize", syncSidebarForViewport);
  syncSidebarForViewport();
  updateSliderLabels();
})();
