/**
 * 播放器控制 + 時間戳跳轉
 */

// 切換影片/音訊播放器
function switchPlayer(mode) {
  var videoContainer = document.getElementById("video-container");
  var audioContainer = document.getElementById("audio-container");
  var buttons = document.querySelectorAll(".player-toggle");

  buttons.forEach(function (btn) {
    btn.classList.toggle("active", btn.dataset.mode === mode);
  });

  if (mode === "video") {
    if (videoContainer) videoContainer.style.display = "";
    if (audioContainer) audioContainer.style.display = "none";
  } else {
    if (videoContainer) videoContainer.style.display = "none";
    if (audioContainer) audioContainer.style.display = "";
  }
}

// 時間戳轉秒數（MM:SS → seconds）
function parseTimestamp(ts) {
  var parts = ts.split(":");
  if (parts.length === 2) {
    return parseInt(parts[0], 10) * 60 + parseInt(parts[1], 10);
  }
  if (parts.length === 3) {
    return parseInt(parts[0], 10) * 3600 + parseInt(parts[1], 10) * 60 + parseInt(parts[2], 10);
  }
  return 0;
}

// 跳轉到指定時間並播放
function seekTo(seconds) {
  var video = document.getElementById("video-player");
  var audio = document.getElementById("audio-player");

  // 判斷目前顯示的播放器
  var videoContainer = document.getElementById("video-container");
  var activePlayer = null;

  if (videoContainer && videoContainer.style.display !== "none") {
    activePlayer = video;
  } else {
    activePlayer = audio;
  }

  if (activePlayer) {
    activePlayer.currentTime = seconds;
    activePlayer.play();
  }
}

// 綁定所有時間戳元素的點擊事件
document.addEventListener("DOMContentLoaded", function () {
  var timestamps = document.querySelectorAll(".ts-link");
  timestamps.forEach(function (el) {
    el.style.cursor = "pointer";
    el.addEventListener("click", function () {
      var time = this.dataset.time || this.textContent;
      seekTo(parseTimestamp(time));
    });
  });
});
