const state = { dashboard: null, questions: [], topics: [], selected: null, selectedSavedProblem: null };
const $ = (selector) => document.querySelector(selector);

async function request(url, options = {}) {
  const response = await fetch(url, { headers: { "Content-Type": "application/json" }, ...options });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Something went wrong.");
  return data;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, char => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", "'":"&#39;", '"':"&quot;" })[char]);
}

function relativeDue(days) {
  if (days < 0) return `overdue by ${-days} day${days === -1 ? "" : "s"}`;
  if (days === 0) return "due today";
  return `due in ${days} day${days === 1 ? "" : "s"}`;
}

function renderDashboard() {
  const { dashboard } = state;
  $("#solvedCount").textContent = dashboard.total_solved;
  $("#dueCount").textContent = dashboard.due_today;
  $("#topicCount").textContent = dashboard.topics;
  const list = $("#revisionList"); list.innerHTML = "";
  dashboard.problems.forEach(problem => {
    const node = $("#revisionTemplate").content.firstElementChild.cloneNode(true);
    node.querySelector(".tag").textContent = `${problem.topic} · ${problem.difficulty}`;
    node.querySelector("h3").textContent = problem.problem;
    node.querySelector("p").textContent = `${relativeDue(problem.days_until_revision)}${problem.practice_question ? " · prompt ready" : " · add its prompt"}`;
    const practiceButton = node.querySelector('[data-action="practice"]'); practiceButton.disabled = !problem.practice_question;
    practiceButton.textContent = problem.practice_question ? "Practice" : "No prompt yet";
    practiceButton.addEventListener("click", () => selectQuestion(problem.practice_question, problem.problem));
    node.querySelector('[data-action="delete"]').addEventListener("click", () => deleteSolution(problem.problem));
    list.append(node);
  });
}

function renderQuestions() {
  const term = $("#questionFilter").value.toLowerCase().trim();
  const topic = $("#practiceTopicFilter").value;
  const difficulty = $("#practiceDifficultyFilter").value;
  const list = $("#questionList"); list.innerHTML = "";
  state.questions.filter(q =>
    `${q.title} ${q.topic} ${q.difficulty}`.toLowerCase().includes(term) &&
    (!topic || q.topic === topic) && (!difficulty || q.difficulty === difficulty)
  ).forEach(question => {
    const button = document.createElement("button"); button.className = "question-button";
    button.innerHTML = `<strong>${escapeHtml(question.title)}</strong><span>${escapeHtml(question.topic)} · ${escapeHtml(question.difficulty)}</span>`;
    button.addEventListener("click", () => selectQuestion(question)); list.append(button);
  });
}

function renderTopics() {
  const select = $("#uploadTopic");
  select.innerHTML = state.topics.map(topic => `<option value="${escapeHtml(topic.name)}">${escapeHtml(topic.name)}</option>`).join("") + '<option value="__new__">+ Create new category</option>';
  const practiceFilter = $("#practiceTopicFilter");
  const selected = practiceFilter.value;
  const questionTopics = [...new Set(state.questions.map(question => question.topic))].sort();
  practiceFilter.innerHTML = '<option value="">All folders</option>' + questionTopics.map(topic => `<option value="${escapeHtml(topic)}">${escapeHtml(topic)}</option>`).join("");
  practiceFilter.value = questionTopics.includes(selected) ? selected : "";
}

function starterCode(question) {
  if (question.runner === "class_method") return `class Solution:\n    def ${question.method}(self, *args):\n        # Replace *args with clear parameter names, then write your solution.\n        pass\n`;
  return "# Read input, solve the problem, and print the answer.\n";
}

function renderExamples(question) {
  const extracted = Array.isArray(question.examples) && question.examples.length ? question.examples : null;
  const examples = extracted || (question.tests || []).slice(0, 3).map((test, index) => ({
    label: `Example ${index + 1}`,
    input: JSON.stringify(test.args ?? test.input ?? ""),
    output: JSON.stringify(test.expected),
  }));
  const node = $("#problemExamples");
  if (!examples.length) {
    node.innerHTML = '<p class="muted">No examples were included with this upload.</p>';
    return;
  }
  node.innerHTML = examples.map((example, index) => {
    const fields = [["Input", example.input], ["Output", example.output], ["Explanation", example.explanation]]
      .filter(([, value]) => value)
      .map(([label, value]) => `<div><strong>${label}</strong><code>${escapeHtml(value)}</code></div>`).join("");
    return `<article class="example-card"><h4>${escapeHtml(example.label || `Example ${index + 1}`)}</h4>${fields}</article>`;
  }).join("");
}

function selectQuestion(question, savedProblem = null) {
  state.selected = question; state.selectedSavedProblem = savedProblem;
  $("#practiceArea").classList.remove("hidden");
  $("#problemMeta").textContent = `${question.topic.toUpperCase()} · ${question.difficulty.toUpperCase()}`;
  $("#problemTitle").textContent = question.title;
  $("#problemPrompt").textContent = question.prompt;
  $("#problemConstraints").textContent = question.constraints;
  $("#edgeCases").innerHTML = question.edge_cases.map(item => `<li>${escapeHtml(item)}</li>`).join("");
  renderExamples(question);
  $("#solutionHint").textContent = question.runner === "class_method" ? `Create class Solution with method ${question.method}(...)` : "Read standard input and print only the final answer.";
  $("#codeEditor").value = localStorage.getItem(`dsa-draft:${question.id}`) || starterCode(question); $("#testResults").className = "test-results muted"; $("#testResults").textContent = "Your test results will appear here.";
  $("#markRevised").classList.toggle("hidden", !savedProblem);
  $("#submitPractice").classList.toggle("hidden", !question.source_path);
  $("#practiceArea").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function runTests() {
  const results = $("#testResults"); results.className = "test-results muted"; results.textContent = "Running tests…";
  try {
    const data = await request("/api/check", { method: "POST", body: JSON.stringify({ question_id: state.selected.id, code: $("#codeEditor").value }) });
    results.className = "test-results";
    results.innerHTML = `<strong class="${data.passed === data.total ? "result-pass" : "result-fail"}">${data.passed}/${data.total} tests passed</strong>` + data.results.map(item => `<div class="result-line ${item.passed ? "result-pass" : "result-fail"}">${item.passed ? "PASS" : "FAIL"} ${item.number} — expected ${escapeHtml(JSON.stringify(item.expected))}, got ${escapeHtml(JSON.stringify(item.actual))}</div>`).join("");
  } catch (error) { results.className = "test-results result-fail"; results.textContent = error.message; }
}

async function markRevised() {
  try {
    const data = await request("/api/mark-revised", { method: "POST", body: JSON.stringify({ problem: state.selectedSavedProblem }) });
    state.dashboard = data.dashboard; renderDashboard(); alert(`Saved. ${data.message}`);
  } catch (error) { alert(error.message); }
}

async function submitPractice() {
  if (!state.selected) return;
  const button = $("#submitPractice");
  button.disabled = true; button.textContent = "Submitting…";
  try {
    const data = await request("/api/practice-submit", { method: "POST", body: JSON.stringify({ question_id: state.selected.id, code: $("#codeEditor").value }) });
    state.dashboard = data.dashboard; state.questions = data.questions;
    state.selectedSavedProblem = data.saved_problem;
    renderDashboard(); renderQuestions();
    $("#markRevised").classList.remove("hidden");
    $("#testResults").className = "test-results result-pass";
    $("#testResults").textContent = data.message;
  } catch (error) {
    $("#testResults").className = "test-results result-fail";
    $("#testResults").textContent = error.message;
  } finally { button.disabled = false; button.textContent = "Submit solution & commit"; }
}

function toggleNewTopic() {
  const isNew = $("#uploadTopic").value === "__new__";
  $("#newTopicField").classList.toggle("hidden", !isNew);
  $("#uploadNewTopic").required = isNew;
}

async function uploadSolution(event) {
  event.preventDefault();
  const message = $("#uploadMessage"); message.className = "muted"; message.textContent = "Saving…";
  const uploadedProblem = $("#uploadProblem").value;
  const topic = $("#uploadTopic").value === "__new__" ? $("#uploadNewTopic").value : $("#uploadTopic").value;
  const questionDetail = $("#uploadQuestionDetail").value.trim();
  try {
    const data = await request("/api/upload", { method: "POST", body: JSON.stringify({ problem: uploadedProblem, topic, difficulty: $("#uploadDifficulty").value, code: $("#uploadCode").value, question_detail: questionDetail }) });
    state.dashboard = data.dashboard; state.topics = data.topics;
    state.questions = (await request("/api/questions")).questions;
    renderDashboard(); renderQuestions(); renderTopics();
    const testMessage = data.test_cases ? ` ${data.test_cases} test case${data.test_cases === 1 ? "" : "s"} ready.` : "";
    message.className = "result-pass"; message.textContent = `${data.message}${data.prompt_added ? " Revision prompt created." : ""}${testMessage}`;
    $("#uploadForm").reset(); toggleNewTopic();
    if (data.question) selectQuestion(data.question, uploadedProblem);
  } catch (error) { message.className = "result-fail"; message.textContent = error.message; }
}

async function deleteSolution(problem) {
  if (!confirm(`Delete '${problem}'? This removes its saved solution file and revision entry.`)) return;
  try {
    const data = await request("/api/delete-solution", { method: "POST", body: JSON.stringify({ problem }) });
    state.dashboard = data.dashboard; renderDashboard();
    if (state.selectedSavedProblem === problem) $("#practiceArea").classList.add("hidden");
  } catch (error) { alert(error.message); }
}

async function initialise() {
  try {
    const [dashboard, questionData, topicData] = await Promise.all([request("/api/dashboard"), request("/api/questions"), request("/api/topics")]);
    state.dashboard = dashboard; state.questions = questionData.questions; state.topics = topicData.topics; renderDashboard(); renderQuestions(); renderTopics();
  } catch (error) { $("#revisionList").innerHTML = `<p class="result-fail">Could not load your DSA data: ${escapeHtml(error.message)}</p>`; }
}

$("#refreshButton").addEventListener("click", initialise);
$("#questionFilter").addEventListener("input", renderQuestions);
$("#practiceTopicFilter").addEventListener("change", renderQuestions);
$("#practiceDifficultyFilter").addEventListener("change", renderQuestions);
$("#runTests").addEventListener("click", runTests);
$("#submitPractice").addEventListener("click", submitPractice);
$("#markRevised").addEventListener("click", markRevised);
$("#closePractice").addEventListener("click", () => $("#practiceArea").classList.add("hidden"));
$("#uploadTopic").addEventListener("change", toggleNewTopic);
$("#uploadForm").addEventListener("submit", uploadSolution);
$("#codeEditor").addEventListener("input", event => {
  if (state.selected) localStorage.setItem(`dsa-draft:${state.selected.id}`, event.target.value);
});
initialise();
