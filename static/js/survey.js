let startTime;

function startTimer() {
  startTime = new Date().getTime();
}

function recordTime() {
  let endTime = new Date().getTime();
  let timeSpent = endTime - startTime; // time in milliseconds
  document.getElementById('view_time').value = timeSpent;
}
