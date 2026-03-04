// Calabi-Yau 流形動畫（p5.js）— 首頁標題旁裝飾
(function () {
  var SIZE = 230;
  var container = document.getElementById('calabi-yau');
  if (!container) return;

  var script = document.createElement('script');
  script.src = 'https://cdn.jsdelivr.net/npm/p5@1/lib/p5.min.js';
  script.async = true;
  script.onload = function () {
    new p5(function (p) {
      var n = 5;
      var angle = 0;

      p.setup = function () {
        var canvas = p.createCanvas(SIZE, SIZE);
        canvas.style('display', 'block');
        p.colorMode(p.HSB, 360, 100, 100, 100);
        p.noFill();
      };

      p.draw = function () {
        p.background(215, 43, 9, 25);
        p.translate(p.width / 2, p.height / 2);
        p.rotate(angle * 0.1);

        var scale = SIZE * 0.28;

        for (var k = 0; k < n; k++) {
          var hue = (k * 360 / n + angle * 20) % 360;

          p.beginShape();
          p.stroke(hue, 70, 100, 70);
          p.strokeWeight(1.4);

          var steps = 200;
          for (var i = 0; i <= steps; i++) {
            var alpha = (i / steps) * p.TWO_PI;
            var z1Re = Math.cos(alpha);
            var z1Im = Math.sin(alpha);
            var r = Math.pow(Math.sqrt(z1Re * z1Re + z1Im * z1Im), 1 / n);
            var theta = (Math.atan2(z1Im, z1Re) + 2 * Math.PI * k) / n;
            var x = r * Math.cos(theta + angle * 0.5);
            var y = r * Math.sin(theta + angle * 0.3);
            var twist = Math.sin(alpha * n + angle * 2) * 0.3;
            var px = (x * Math.cos(twist) - y * Math.sin(twist)) * scale;
            var py = (x * Math.sin(twist) + y * Math.cos(twist)) * scale;
            p.vertex(px, py);
          }
          p.endShape();

          p.beginShape();
          p.stroke(hue, 50, 85, 40);
          p.strokeWeight(0.8);

          for (var j = 0; j <= steps; j++) {
            var alpha2 = (j / steps) * p.TWO_PI;
            var r2 = Math.pow(0.7 + 0.3 * Math.sin(alpha2 * n), 1 / n);
            var theta2 = (alpha2 + 2 * Math.PI * k) / n;
            var x2 = r2 * Math.cos(theta2 + angle * 0.7);
            var y2 = r2 * Math.sin(theta2 + angle * 0.5);
            var twist2 = Math.cos(alpha2 * n - angle) * 0.4;
            var px2 = (x2 * Math.cos(twist2) - y2 * Math.sin(twist2)) * scale * 0.8;
            var py2 = (x2 * Math.sin(twist2) + y2 * Math.cos(twist2)) * scale * 0.8;
            p.vertex(px2, py2);
          }
          p.endShape();
        }

        angle += 0.005;
      };
    }, container);
  };

  document.body.appendChild(script);
})();
