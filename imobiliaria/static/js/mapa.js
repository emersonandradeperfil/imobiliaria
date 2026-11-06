// Mapa do imóvel. Deslogado: círculo de ~800 m (zoom limitado). Logado: pino na posição exata.
(function () {
  var el = document.getElementById("mapa");
  if (!el || !window.L) return;
  var lat = parseFloat(el.dataset.lat), lng = parseFloat(el.dataset.lng);
  if (isNaN(lat) || isNaN(lng)) return;
  var exato = el.dataset.exato === "1";
  var map = L.map(el, { scrollWheelZoom: false, maxZoom: exato ? 19 : 15 }).setView([lat, lng], exato ? 16 : 14);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: exato ? 19 : 15,
    attribution: "&copy; OpenStreetMap"
  }).addTo(map);
  if (exato) {
    L.marker([lat, lng]).addTo(map);
  } else {
    L.circle([lat, lng], { radius: 800, color: "#b08d57", fillColor: "#b08d57", fillOpacity: 0.2 }).addTo(map);
  }
})();
