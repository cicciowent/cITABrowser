# -*- coding: utf-8 -*-
"""
pdf_viewer_tab.py — Scheda Browser per Visualizzazione e Modifica PDF (cITA PDF Studio)
Fornisce:
- Reader integrato con visualizzazione fluida a pagine
- Strumenti avanzati di annotazione e disegno (Penna, Evidenziatore, Gomma)
- Inserimento box di testo mobili e riposizionabili (Drag & Drop)
- Personalizzazione testo: Font (Sans, Serif, Mono), Dimensione, Grassetto, Corsivo, Sottolineato, Colore
- Scelta sfondo del testo (Trasparente o Bianco Coprente per coprire testi sottostanti)
- Salvataggio nativo con proposta percorso nella stessa cartella di origine del documento
"""

import os
import json
import base64
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QMessageBox
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtCore import QUrl, Qt, Signal, QObject, Slot

PDF_STUDIO_HTML = """<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>cITA PDF Studio</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script>
<script src="https://unpkg.com/pdf-lib@1.17.1/dist/pdf-lib.min.js"></script>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: #0B192C;
    color: #F8FAFC;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    display: flex;
    flex-direction: column;
    height: 100vh;
    overflow: hidden;
  }
  #toolbar {
    background: #1E3E62;
    border-bottom: 2px solid #005CA8;
    padding: 8px 14px;
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    z-index: 1000;
    box-shadow: 0 2px 10px rgba(0,0,0,0.3);
  }
  .tool-group {
    display: flex;
    align-items: center;
    gap: 4px;
    background: rgba(0, 0, 0, 0.2);
    padding: 3px 6px;
    border-radius: 6px;
  }
  .tool-btn {
    background: #F1F5F9;
    color: #0F172A;
    border: 1px solid #CBD5E1;
    border-radius: 4px;
    padding: 5px 10px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 4px;
    transition: all 0.15s;
    user-select: none;
  }
  .tool-btn:hover { background: #FFFFFF; color: #005CA8; }
  .tool-btn.active { background: #005CA8; color: #FFFFFF; border-color: #FFDF00; }
  .tool-btn.toggle-btn.active { background: #FFDF00; color: #000000; border-color: #B8860B; }
  .tool-btn.save { background: #FFDF00; color: #000000; border-color: #E5C700; font-weight: bold; }
  .tool-btn.save:hover { background: #FFE633; }
  .tool-btn.clear { background: #EF4444; color: #FFFFFF; border-color: #DC2626; }
  .tool-btn.clear:hover { background: #DC2626; }
  .tool-btn.print {
    background: #005CA8;
    color: #FFFFFF;
    border-color: #004B87;
    font-weight: bold;
  }
  .tool-btn.print:hover {
    background: #0073D1;
  }
  .separator { width: 1px; height: 26px; background: rgba(255, 255, 255, 0.2); margin: 0 4px; }
  
  select, input[type="color"] {
    background: #F8FAFC;
    color: #0F172A;
    border: 1px solid #CBD5E1;
    border-radius: 4px;
    padding: 4px 6px;
    font-size: 12px;
    font-weight: 600;
    height: 28px;
    cursor: pointer;
  }
  input[type="color"] {
    width: 32px;
    padding: 1px 2px;
  }
  
  #viewer-container {
    flex: 1;
    overflow: auto;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 24px;
    background: #0E2238;
    gap: 24px;
    scroll-behavior: smooth;
  }
  .page-wrapper {
    position: relative;
    box-shadow: 0 6px 20px rgba(0,0,0,0.4);
    background: white;
    border-radius: 4px;
    user-select: none;
  }
  canvas.pdf-canvas { display: block; }
  canvas.draw-canvas {
    position: absolute;
    top: 0; left: 0;
    z-index: 10;
  }
  
  /* Text box draggable container */
  .pdf-text-box {
    position: absolute;
    z-index: 50;
    min-width: 60px;
    min-height: 24px;
    border: 1.5px dashed transparent;
    border-radius: 4px;
    background: transparent;
    cursor: default;
    display: flex;
    flex-direction: column;
    box-sizing: border-box;
    transition: border 0.12s ease-in-out;
  }
  .pdf-text-box .pdf-text-box-header {
    display: none;
  }
  .pdf-text-box.selected {
    border: 1.5px dashed #005CA8;
    box-shadow: 0 2px 10px rgba(0, 92, 168, 0.25);
    z-index: 100;
  }
  .pdf-text-box.selected .pdf-text-box-header {
    display: flex;
  }
  .pdf-text-box:hover:not(.selected) {
    border: 1.5px dotted rgba(0, 92, 168, 0.45);
    cursor: pointer;
  }
  .pdf-text-box.bg-white {
    background: #FFFFFF !important;
  }
  .pdf-text-box-header {
    background: #1E3E62;
    color: #FFFFFF;
    font-size: 10px;
    padding: 2px 6px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    cursor: move;
    user-select: none;
    border-top-left-radius: 2px;
    border-top-right-radius: 2px;
  }
  .pdf-text-box-del {
    color: #EF4444;
    font-weight: bold;
    cursor: pointer;
    padding: 0 4px;
    font-size: 11px;
  }
  .pdf-text-box-del:hover {
    color: #FF7878;
  }
  .pdf-text-box-content {
    flex: 1;
    padding: 4px 6px;
    outline: none;
    user-select: text;
    white-space: pre-wrap;
    word-break: break-word;
    font-size: 14px;
    color: #000000;
  }
  
  #status-bar {
    background: #1E3E62;
    padding: 5px 16px;
    font-size: 12px;
    color: #CBD5E1;
    border-top: 1px solid #005CA8;
    display: flex;
    justify-content: space-between;
  }

  @media print {
    body {
      background: #FFFFFF !important;
      color: #000000 !important;
      overflow: visible !important;
      height: auto !important;
    }
    #toolbar, #status-bar, .pdf-text-box-header {
      display: none !important;
    }
    #viewer-container {
      background: #FFFFFF !important;
      padding: 0 !important;
      margin: 0 !important;
      overflow: visible !important;
      display: block !important;
    }
    .page-wrapper {
      box-shadow: none !important;
      margin: 0 0 0 0 !important;
      page-break-after: always !important;
      break-after: page !important;
    }
    .pdf-text-box {
      border: none !important;
      box-shadow: none !important;
    }
  }
</style>
</head>
<body>

<div id="toolbar">
  <!-- Navigazione Pagine -->
  <div class="tool-group">
    <button class="tool-btn" id="btn-prev" onclick="prevPage()" title="Pagina precedente (◀)">◀</button>
    <span id="page-num-display" style="font-size: 12px; font-weight: 600; color: #F8FAFC; min-width: 80px; text-align: center;">Pag. 1 / 1</span>
    <button class="tool-btn" id="btn-next" onclick="nextPage()" title="Pagina successiva (▶)">▶</button>
  </div>

  <!-- Zoom -->
  <div class="tool-group">
    <button class="tool-btn" onclick="zoomIn()" title="Ingrandisci">🔍+ Zoom</button>
    <button class="tool-btn" onclick="zoomOut()" title="Riduci">🔍-</button>
    <button class="tool-btn" onclick="zoomReset()" title="Zoom 100%">100%</button>
  </div>

  <div class="separator"></div>

  <!-- Strumenti Grafici -->
  <div class="tool-group">
    <button class="tool-btn" id="tool-draw" onclick="setTool('draw')">🖋️ Penna</button>
    <button class="tool-btn" id="tool-highlight" onclick="setTool('highlight')">🖍️ Evidenziatore</button>
    <button class="tool-btn" id="tool-text" onclick="setTool('text')">🔤 Inserisci Testo</button>
  </div>

  <!-- Controlli Testo -->
  <div class="tool-group" id="text-controls-group">
    <select id="font-family" title="Carattere / Tipo Font" onchange="applyTextStyleToSelected()">
      <option value="Helvetica" selected>Sans-serif (Helvetica / Arial)</option>
      <option value="TimesRoman">Serif (Times Roman)</option>
      <option value="Courier">Monospazio (Courier)</option>
    </select>

    <select id="font-size" title="Dimensione Carattere" onchange="applyTextStyleToSelected()">
      <option value="10">10 pt</option>
      <option value="12">12 pt</option>
      <option value="14" selected>14 pt</option>
      <option value="16">16 pt</option>
      <option value="18">18 pt</option>
      <option value="20">20 pt</option>
      <option value="24">24 pt</option>
      <option value="28">28 pt</option>
      <option value="32">32 pt</option>
    </select>

    <button class="tool-btn toggle-btn" id="btn-bold" onclick="toggleStyle('bold')" title="Grassetto"><b>B</b></button>
    <button class="tool-btn toggle-btn" id="btn-italic" onclick="toggleStyle('italic')" title="Corsivo"><i>I</i></button>
    <button class="tool-btn toggle-btn" id="btn-underline" onclick="toggleStyle('underline')" title="Sottolineato"><u>U</u></button>

    <input type="color" id="text-color" value="#000000" title="Colore Testo" onchange="applyTextStyleToSelected()">

    <button class="tool-btn toggle-btn" id="btn-bg-white" onclick="toggleBgWhite()" title="Sfondo Bianco Coprente (utile per coprire testi esistenti)">⬜ Sfondo Bianco</button>
  </div>

  <div class="separator"></div>

  <div class="tool-group">
    <button class="tool-btn clear" onclick="clearAllModifications()" title="Cancella tutte le modifiche non salvate">🗑️ Azzera Modifiche</button>
  </div>

  <div style="flex: 1;"></div>

  <!-- Stampa e Salvataggio -->
  <div class="tool-group" style="background: transparent;">
    <button class="tool-btn print" id="btn-print" onclick="printPdf()" title="Stampa documento PDF (Ctrl+P)">🖨️ Stampa</button>
    <button class="tool-btn save" onclick="savePdf()" title="Salva documento PDF modificato">💾 Salva Modifiche</button>
  </div>
</div>

<div id="viewer-container">
  <div id="loading" style="margin-top: 100px; font-size: 16px; color: #94A3B8;">Caricamento documento PDF in corso...</div>
</div>

<div id="status-bar">
  <span id="status-text">Pronto • Fai clic su '🔤 Inserisci Testo' e clicca sulla pagina per aggiungere un box modificabile e spostabile.</span>
  <span id="doc-info">cITA PDF Studio</span>
</div>

<script>
pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';

let pdfDoc = null;
let currentPage = 1;
let totalPages = 1;
let currentScale = 1.3;
let currentTool = 'none';
let pdfBytesArray = null;
let rawPdfBase64 = null;
let pyBridge = null;

// Gestione Stile Testo Corrente
let currentTextStyle = {
  font: 'Helvetica',
  size: 14,
  bold: false,
  italic: false,
  underline: false,
  color: '#000000',
  bgWhite: false
};

let selectedTextBox = null;
let textBoxCounter = 0;

// Setup QWebChannel se presente
if (typeof QWebChannel !== "undefined") {
  new QWebChannel(qt.webChannelTransport, function (channel) {
    pyBridge = channel.objects.pyBridge;
  });
}

function loadPdfFromBase64(b64Data) {
  try {
    rawPdfBase64 = b64Data;
    const raw = atob(b64Data);
    const rawLength = raw.length;
    const array = new Uint8Array(rawLength);
    for (let i = 0; i < rawLength; i++) {
      array[i] = raw.charCodeAt(i);
    }
    pdfBytesArray = array;

    // Clona il buffer per pdfjsLib per evitare che il worker scolleghi (detach) il buffer
    const renderCopy = new Uint8Array(array.length);
    renderCopy.set(array);

    pdfjsLib.getDocument({ data: renderCopy }).promise.then(function(doc) {
      pdfDoc = doc;
      totalPages = doc.numPages;
      currentPage = 1;
      document.getElementById('loading').style.display = 'none';
      renderAllPages();
    }).catch(function(err) {
      document.getElementById('loading').innerText = "Errore caricamento PDF: " + err.message;
    });
  } catch(e) {
    document.getElementById('loading').innerText = "Errore decodifica: " + e.message;
  }
}

function updatePageDisplay() {
  const display = document.getElementById('page-num-display');
  if (display) {
    display.innerText = `Pag. ${currentPage} / ${totalPages}`;
  }
  const btnPrev = document.getElementById('btn-prev');
  const btnNext = document.getElementById('btn-next');
  if (btnPrev) btnPrev.style.opacity = (currentPage <= 1) ? '0.5' : '1.0';
  if (btnNext) btnNext.style.opacity = (currentPage >= totalPages) ? '0.5' : '1.0';
}

function prevPage() {
  if (currentPage > 1) {
    goToPage(currentPage - 1);
  }
}

function nextPage() {
  if (currentPage < totalPages) {
    goToPage(currentPage + 1);
  }
}

function goToPage(pageNum) {
  if (!pdfDoc) return;
  currentPage = Math.max(1, Math.min(pageNum, totalPages));
  updatePageDisplay();
  const target = document.getElementById('page-wrap-' + currentPage);
  if (target) {
    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

let isScrollTrackingActive = false;
function setupScrollTracking() {
  if (isScrollTrackingActive) return;
  isScrollTrackingActive = true;
  const container = document.getElementById('viewer-container');
  if (!container) return;

  let scrollTimeout = null;
  container.addEventListener('scroll', function() {
    if (scrollTimeout) clearTimeout(scrollTimeout);
    scrollTimeout = setTimeout(() => {
      if (!pdfDoc) return;
      const containerRect = container.getBoundingClientRect();
      const centerY = containerRect.top + containerRect.height / 3;

      for (let p = 1; p <= totalPages; p++) {
        const wrap = document.getElementById('page-wrap-' + p);
        if (wrap) {
          const r = wrap.getBoundingClientRect();
          if (r.top <= centerY && r.bottom >= centerY) {
            if (currentPage !== p) {
              currentPage = p;
              updatePageDisplay();
            }
            break;
          }
        }
      }
    }, 40);
  });
}

function renderAllPages() {
  const container = document.getElementById('viewer-container');
  // Conserva i testi attuali mappandoli per pagina prima del re-render se zoom cambia
  const existingBoxes = collectTextBoxData();

  container.innerHTML = '';
  totalPages = pdfDoc ? pdfDoc.numPages : 1;

  for (let pageNum = 1; pageNum <= totalPages; pageNum++) {
    renderSinglePage(pageNum, container, existingBoxes[pageNum] || []);
  }
  updatePageDisplay();
  setupScrollTracking();
}

function renderSinglePage(pageNum, container, savedBoxes = []) {
  pdfDoc.getPage(pageNum).then(function(page) {
    const viewport = page.getViewport({ scale: currentScale });

    const wrapper = document.createElement('div');
    wrapper.className = 'page-wrapper';
    wrapper.id = 'page-wrap-' + pageNum;
    wrapper.dataset.pageNum = pageNum;
    wrapper.dataset.origWidth = page.view[2] - page.view[0];
    wrapper.dataset.origHeight = page.view[3] - page.view[1];
    wrapper.style.width = viewport.width + 'px';
    wrapper.style.height = viewport.height + 'px';

    const pdfCanvas = document.createElement('canvas');
    pdfCanvas.className = 'pdf-canvas';
    pdfCanvas.width = viewport.width;
    pdfCanvas.height = viewport.height;
    const ctx = pdfCanvas.getContext('2d');

    const drawCanvas = document.createElement('canvas');
    drawCanvas.className = 'draw-canvas';
    drawCanvas.id = 'draw-canvas-' + pageNum;
    drawCanvas.width = viewport.width;
    drawCanvas.height = viewport.height;
    setupDrawingOnCanvas(drawCanvas, wrapper, pageNum);

    wrapper.appendChild(pdfCanvas);
    wrapper.appendChild(drawCanvas);
    container.appendChild(wrapper);

    page.render({ canvasContext: ctx, viewport: viewport });

    // Ripristina eventuali box di testo
    savedBoxes.forEach(boxData => {
      createTextBoxElement(wrapper, boxData.x * currentScale, boxData.y * currentScale, boxData);
    });
  });
}

function setupDrawingOnCanvas(canvas, wrapper, pageNum) {
  const ctx = canvas.getContext('2d');
  let isDrawing = false;
  let lastX = 0, lastY = 0;

  wrapper.onclick = function(e) {
    if (currentTool === 'text') {
      // Se si clicca su un box di testo esistente non ne crea uno nuovo
      if (e.target.closest('.pdf-text-box')) return;
      
      const rect = wrapper.getBoundingClientRect();
      const clickX = e.clientX - rect.left;
      const clickY = e.clientY - rect.top;

      createTextBoxElement(wrapper, clickX, clickY);
      setTool('none'); // Torna a modalità selezione
    }
  };

  canvas.onmousedown = function(e) {
    if (currentTool === 'draw' || currentTool === 'highlight') {
      isDrawing = true;
      const rect = canvas.getBoundingClientRect();
      lastX = e.clientX - rect.left;
      lastY = e.clientY - rect.top;
    }
  };

  canvas.onmousemove = function(e) {
    if (!isDrawing) return;
    const rect = canvas.getBoundingClientRect();
    const curX = e.clientX - rect.left;
    const curY = e.clientY - rect.top;

    ctx.beginPath();
    ctx.moveTo(lastX, lastY);
    ctx.lineTo(curX, curY);

    if (currentTool === 'highlight') {
      ctx.strokeStyle = "rgba(255, 235, 59, 0.45)";
      ctx.lineWidth = 18 * currentScale;
      ctx.lineCap = "square";
    } else {
      ctx.strokeStyle = "#005CA8";
      ctx.lineWidth = 2.5 * currentScale;
      ctx.lineCap = "round";
    }
    ctx.stroke();

    lastX = curX;
    lastY = curY;
  };

  canvas.onmouseup = function() { isDrawing = false; };
  canvas.onmouseleave = function() { isDrawing = false; };
}

function createTextBoxElement(wrapper, x, y, initialData = null) {
  textBoxCounter++;
  const boxId = 'text-box-' + textBoxCounter;

  const box = document.createElement('div');
  box.className = 'pdf-text-box' + ((initialData && initialData.bgWhite) || (!initialData && currentTextStyle.bgWhite) ? ' bg-white' : '');
  box.id = boxId;
  box.style.left = Math.max(0, Math.min(x, wrapper.clientWidth - 150)) + 'px';
  box.style.top = Math.max(0, Math.min(y, wrapper.clientHeight - 40)) + 'px';

  // Salvataggio stile nei dataset
  const font = initialData ? initialData.font : currentTextStyle.font;
  const size = initialData ? initialData.size : currentTextStyle.size;
  const bold = initialData ? initialData.bold : currentTextStyle.bold;
  const italic = initialData ? initialData.italic : currentTextStyle.italic;
  const underline = initialData ? initialData.underline : currentTextStyle.underline;
  const color = initialData ? initialData.color : currentTextStyle.color;
  const bgWhite = initialData ? initialData.bgWhite : currentTextStyle.bgWhite;

  box.dataset.font = font;
  box.dataset.size = size;
  box.dataset.bold = bold;
  box.dataset.italic = italic;
  box.dataset.underline = underline;
  box.dataset.color = color;
  box.dataset.bgWhite = bgWhite;

  // Header / Maniglia di trascinamento
  const header = document.createElement('div');
  header.className = 'pdf-text-box-header';
  header.innerHTML = `<span>✥ Trascina</span><span class="pdf-text-box-del" title="Elimina testo">✖</span>`;

  // Contenuto modificabile
  const content = document.createElement('div');
  content.className = 'pdf-text-box-content';
  content.contentEditable = "true";
  content.innerText = initialData ? initialData.text : "Scrivi qui il testo...";

  applyStylesToContentElement(content, box.dataset);

  header.querySelector('.pdf-text-box-del').onclick = function(e) {
    e.stopPropagation();
    box.remove();
    if (selectedTextBox === box) selectedTextBox = null;
  };

  // Drag & Drop
  makeDraggable(box, header, wrapper);

  // Selezione per personalizzazione
  box.onclick = function(e) {
    e.stopPropagation();
    selectTextBox(box);
  };
  content.onfocus = function() {
    selectTextBox(box);
  };

  box.appendChild(header);
  box.appendChild(content);
  wrapper.appendChild(box);

  selectTextBox(box);
  if (!initialData) {
    setTimeout(() => {
      content.focus();
      // Seleziona tutto il testo per sovrascrivere subito
      document.execCommand('selectAll', false, null);
    }, 50);
  }
}

function applyStylesToContentElement(content, styleData) {
  let fontFam = "sans-serif";
  if (styleData.font === "TimesRoman") fontFam = '"Times New Roman", Times, serif';
  else if (styleData.font === "Courier") fontFam = '"Courier New", Courier, monospace';

  content.style.fontFamily = fontFam;
  content.style.fontSize = (parseFloat(styleData.size) * currentScale) + "px";
  content.style.fontWeight = (styleData.bold === "true" || styleData.bold === true) ? "bold" : "normal";
  content.style.fontStyle = (styleData.italic === "true" || styleData.italic === true) ? "italic" : "normal";
  content.style.textDecoration = (styleData.underline === "true" || styleData.underline === true) ? "underline" : "none";
  content.style.color = styleData.color;
}

function selectTextBox(box) {
  document.querySelectorAll('.pdf-text-box').forEach(b => b.classList.remove('selected'));
  selectedTextBox = box;
  if (box) {
    box.classList.add('selected');
    // Aggiorna controlli barra strumenti
    document.getElementById('font-family').value = box.dataset.font;
    document.getElementById('font-size').value = box.dataset.size;
    document.getElementById('text-color').value = box.dataset.color;

    const isBold = box.dataset.bold === "true" || box.dataset.bold === true;
    const isItalic = box.dataset.italic === "true" || box.dataset.italic === true;
    const isUnderline = box.dataset.underline === "true" || box.dataset.underline === true;
    const isBgWhite = box.dataset.bgWhite === "true" || box.dataset.bgWhite === true;

    setBtnActive('btn-bold', isBold);
    setBtnActive('btn-italic', isItalic);
    setBtnActive('btn-underline', isUnderline);
    setBtnActive('btn-bg-white', isBgWhite);
  }
}

// Deseleziona e mimetizza le caselle di testo quando si clicca altrove sul documento
document.addEventListener('mousedown', function(e) {
  if (!e.target.closest('.pdf-text-box') && !e.target.closest('#toolbar')) {
    selectTextBox(null);
  }
});

function makeDraggable(box, handle, container) {
  let isDragging = false;
  let startX, startY, startLeft, startTop;

  handle.onmousedown = function(e) {
    isDragging = true;
    startX = e.clientX;
    startY = e.clientY;
    startLeft = parseInt(box.style.left, 10) || 0;
    startTop = parseInt(box.style.top, 10) || 0;

    document.onmousemove = function(ev) {
      if (!isDragging) return;
      const dx = ev.clientX - startX;
      const dy = ev.clientY - startY;

      let newLeft = startLeft + dx;
      let newTop = startTop + dy;

      newLeft = Math.max(0, Math.min(newLeft, container.clientWidth - box.offsetWidth));
      newTop = Math.max(0, Math.min(newTop, container.clientHeight - box.offsetHeight));

      box.style.left = newLeft + 'px';
      box.style.top = newTop + 'px';
    };

    document.onmouseup = function() {
      isDragging = false;
      document.onmousemove = null;
      document.onmouseup = null;
    };
  };
}

function applyTextStyleToSelected() {
  currentTextStyle.font = document.getElementById('font-family').value;
  currentTextStyle.size = parseInt(document.getElementById('font-size').value, 10);
  currentTextStyle.color = document.getElementById('text-color').value;

  if (selectedTextBox) {
    selectedTextBox.dataset.font = currentTextStyle.font;
    selectedTextBox.dataset.size = currentTextStyle.size;
    selectedTextBox.dataset.color = currentTextStyle.color;
    const content = selectedTextBox.querySelector('.pdf-text-box-content');
    if (content) applyStylesToContentElement(content, selectedTextBox.dataset);
  }
}

function toggleStyle(prop) {
  if (prop === 'bold') currentTextStyle.bold = !currentTextStyle.bold;
  if (prop === 'italic') currentTextStyle.italic = !currentTextStyle.italic;
  if (prop === 'underline') currentTextStyle.underline = !currentTextStyle.underline;

  if (selectedTextBox) {
    selectedTextBox.dataset[prop] = currentTextStyle[prop];
    const content = selectedTextBox.querySelector('.pdf-text-box-content');
    if (content) applyStylesToContentElement(content, selectedTextBox.dataset);
  }
  setBtnActive('btn-' + prop, currentTextStyle[prop]);
}

function toggleBgWhite() {
  currentTextStyle.bgWhite = !currentTextStyle.bgWhite;
  if (selectedTextBox) {
    selectedTextBox.dataset.bgWhite = currentTextStyle.bgWhite;
    if (currentTextStyle.bgWhite) {
      selectedTextBox.classList.add('bg-white');
    } else {
      selectedTextBox.classList.remove('bg-white');
    }
  }
  setBtnActive('btn-bg-white', currentTextStyle.bgWhite);
}

function setBtnActive(btnId, active) {
  const btn = document.getElementById(btnId);
  if (!btn) return;
  if (active) btn.classList.add('active');
  else btn.classList.remove('active');
}

function setTool(tool) {
  currentTool = (currentTool === tool) ? 'none' : tool;
  document.querySelectorAll('.tool-btn').forEach(b => {
    if (b.id && b.id.startsWith('tool-')) b.classList.remove('active');
  });
  if (currentTool !== 'none') {
    const btn = document.getElementById('tool-' + tool);
    if (btn) btn.classList.add('active');
    document.getElementById('status-text').innerText =
      tool === 'text' ? "Modalità Testo attiva: fai clic sul punto della pagina in cui vuoi posizionare la scritta." :
      tool === 'draw' ? "Modalità Penna attiva: disegna o firma a mano libera." :
      tool === 'highlight' ? "Modalità Evidenziatore attiva: evidenzia porzioni del documento." : "Pronto.";
  } else {
    document.getElementById('status-text').innerText = "Pronto • Seleziona o trascina gli elementi.";
  }
}

function collectTextBoxData() {
  const data = {};
  document.querySelectorAll('.page-wrapper').forEach(wrapper => {
    const pageNum = parseInt(wrapper.dataset.pageNum, 10);
    data[pageNum] = [];
    wrapper.querySelectorAll('.pdf-text-box').forEach(box => {
      const content = box.querySelector('.pdf-text-box-content');
      data[pageNum].push({
        x: (parseInt(box.style.left, 10) || 0) / currentScale,
        y: (parseInt(box.style.top, 10) || 0) / currentScale,
        width: box.offsetWidth / currentScale,
        height: box.offsetHeight / currentScale,
        text: content ? content.innerText : '',
        font: box.dataset.font,
        size: parseInt(box.dataset.size, 10) || 14,
        bold: box.dataset.bold === "true" || box.dataset.bold === true,
        italic: box.dataset.italic === "true" || box.dataset.italic === true,
        underline: box.dataset.underline === "true" || box.dataset.underline === true,
        color: box.dataset.color || '#000000',
        bgWhite: box.dataset.bgWhite === "true" || box.dataset.bgWhite === true
      });
    });
  });
  return data;
}

function zoomIn() { currentScale = Math.min(3.0, currentScale + 0.2); renderAllPages(); }
function zoomOut() { currentScale = Math.max(0.6, currentScale - 0.2); renderAllPages(); }
function zoomReset() { currentScale = 1.0; renderAllPages(); }

function clearAllModifications() {
  if (!confirm("Sei sicuro di voler azzerare tutte le modifiche e le annotazioni non salvate?")) return;
  document.querySelectorAll('canvas.draw-canvas').forEach(c => {
    const ctx = c.getContext('2d');
    ctx.clearRect(0, 0, c.width, c.height);
  });
  document.querySelectorAll('.pdf-text-box').forEach(b => b.remove());
  selectedTextBox = null;
}

function hexToRgb(hex) {
  const clean = hex.replace('#', '');
  const bigint = parseInt(clean, 16);
  return {
    r: ((bigint >> 16) & 255) / 255,
    g: ((bigint >> 8) & 255) / 255,
    b: (bigint & 255) / 255
  };
}

async function generateCurrentPdfBase64() {
  if (!rawPdfBase64 && !pdfBytesArray) {
    throw new Error("Nessun documento caricato.");
  }
  let pdfDocMod;
  if (rawPdfBase64) {
    pdfDocMod = await PDFLib.PDFDocument.load(rawPdfBase64);
  } else {
    pdfDocMod = await PDFLib.PDFDocument.load(pdfBytesArray);
  }
  const pages = pdfDocMod.getPages();

  // Cache font incorporati
  const fontCache = {};
  async function getFont(family, bold, italic) {
    let key = family;
    if (family === 'Helvetica') {
      if (bold && italic) key = 'HelveticaBoldOblique';
      else if (bold) key = 'HelveticaBold';
      else if (italic) key = 'HelveticaOblique';
      else key = 'Helvetica';
    } else if (family === 'TimesRoman') {
      if (bold && italic) key = 'TimesRomanBoldItalic';
      else if (bold) key = 'TimesRomanBold';
      else if (italic) key = 'TimesRomanItalic';
      else key = 'TimesRoman';
    } else if (family === 'Courier') {
      if (bold && italic) key = 'CourierBoldOblique';
      else if (bold) key = 'CourierBold';
      else if (italic) key = 'CourierOblique';
      else key = 'Courier';
    }
    if (!fontCache[key]) {
      fontCache[key] = await pdfDocMod.embedFont(PDFLib.StandardFonts[key]);
    }
    return fontCache[key];
  }

  const boxesByPage = collectTextBoxData();

  for (let pageNum = 1; pageNum <= pages.length; pageNum++) {
    const targetPage = pages[pageNum - 1];
    const { width: pWidth, height: pHeight } = targetPage.getSize();

    // 1. Applica disegni / annotazioni grafiche se presenti
    const drawCanvas = document.getElementById('draw-canvas-' + pageNum);
    if (drawCanvas) {
      const ctx = drawCanvas.getContext('2d');
      const imgData = ctx.getImageData(0, 0, drawCanvas.width, drawCanvas.height).data;
      let hasDrawing = false;
      for (let i = 3; i < imgData.length; i += 4) {
        if (imgData[i] > 0) { hasDrawing = true; break; }
      }
      if (hasDrawing) {
        const pngUrl = drawCanvas.toDataURL('image/png');
        const pngImageBytes = await fetch(pngUrl).then(res => res.arrayBuffer());
        const embeddedPng = await pdfDocMod.embedPng(pngImageBytes);
        targetPage.drawImage(embeddedPng, {
          x: 0,
          y: 0,
          width: pWidth,
          height: pHeight
        });
      }
    }

    // 2. Applica Box di Testo
    const pageBoxes = boxesByPage[pageNum] || [];
    for (const box of pageBoxes) {
      if (!box.text || !box.text.trim()) continue;

      const font = await getFont(box.font, box.bold, box.italic);
      const rgbColor = hexToRgb(box.color);
      const fontSize = box.size;

      // Coordinate PDF: Y parte dal basso
      const boxX = box.x;
      const boxY = pHeight - box.y - box.height;

      // Sfondo bianco opaco se richiesto
      if (box.bgWhite) {
        targetPage.drawRectangle({
          x: boxX,
          y: boxY,
          width: box.width,
          height: box.height,
          color: PDFLib.rgb(1, 1, 1),
          opacity: 1.0
        });
      }

      // Calcola linee di testo
      const lines = box.text.split('\\n');
      const lineHeight = fontSize * 1.25;
      let currentTextY = pHeight - box.y - fontSize - 4;

      for (const line of lines) {
        if (line.length > 0) {
          targetPage.drawText(line, {
            x: boxX + 6,
            y: currentTextY,
            size: fontSize,
            font: font,
            color: PDFLib.rgb(rgbColor.r, rgbColor.g, rgbColor.b)
          });

          // Sottolineatura se richiesta
          if (box.underline) {
            const textWidth = font.widthOfTextAtSize(line, fontSize);
            targetPage.drawLine({
              start: { x: boxX + 6, y: currentTextY - 2 },
              end: { x: boxX + 6 + textWidth, y: currentTextY - 2 },
              thickness: 1,
              color: PDFLib.rgb(rgbColor.r, rgbColor.g, rgbColor.b)
            });
          }
        }
        currentTextY -= lineHeight;
      }
    }
  }

  return await pdfDocMod.saveAsBase64({ dataUri: false });
}

async function savePdf() {
  if (!rawPdfBase64 && !pdfBytesArray) {
    alert("Nessun documento caricato.");
    return;
  }
  document.getElementById('status-text').innerText = "Generazione PDF in corso...";

  try {
    const base64Saved = await generateCurrentPdfBase64();
    document.getElementById('status-text').innerText = "Salvataggio documento in corso...";

    // Passaggio a Python tramite WebChannel o fallback
    if (pyBridge && typeof pyBridge.savePdfBase64 === "function") {
      pyBridge.savePdfBase64(base64Saved);
    } else {
      const byteCharacters = atob(base64Saved);
      const byteNumbers = new Array(byteCharacters.length);
      for (let i = 0; i < byteCharacters.length; i++) {
        byteNumbers[i] = byteCharacters.charCodeAt(i);
      }
      const byteArray = new Uint8Array(byteNumbers);
      const blob = new Blob([byteArray], { type: 'application/pdf' });
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = 'documento_modificato.pdf';
      link.click();
    }
    document.getElementById('status-text').innerText = "Pronto • Documento salvato.";
  } catch(err) {
    alert("Errore durante il salvataggio: " + err.message);
    document.getElementById('status-text').innerText = "Errore salvataggio: " + err.message;
  }
}

async function printPdf() {
  if (!rawPdfBase64 && !pdfBytesArray) {
    alert("Nessun documento caricato da stampare.");
    return;
  }
  document.getElementById('status-text').innerText = "Preparazione documento per la stampa...";

  try {
    const base64Data = await generateCurrentPdfBase64();
    if (pyBridge && typeof pyBridge.printPdfBase64 === "function") {
      pyBridge.printPdfBase64(base64Data);
    } else {
      window.print();
    }
    document.getElementById('status-text').innerText = "Pronto • Finestra di stampa aperta.";
  } catch(err) {
    alert("Errore durante la preparazione alla stampa: " + err.message);
    document.getElementById('status-text').innerText = "Errore stampa: " + err.message;
  }
}

// Scorciatoie da tastiera
window.addEventListener('keydown', function(e) {
  if ((e.ctrlKey || e.metaKey) && (e.key === 'p' || e.key === 'P')) {
    e.preventDefault();
    printPdf();
  }
  if ((e.ctrlKey || e.metaKey) && (e.key === 's' || e.key === 'S')) {
    e.preventDefault();
    savePdf();
  }
});
</script>
</body>
</html>
"""


class PdfBridge(QObject):
    """Bridge QtWebChannel per la comunicazione tra JavaScript e Python."""
    
    def __init__(self, tab_instance):
        super().__init__()
        self.tab = tab_instance

    @Slot(str)
    def savePdfBase64(self, b64_str: str):
        self.tab.salva_pdf_bytes(b64_str)

    @Slot(str)
    def printPdfBase64(self, b64_str: str):
        self.tab.stampa_pdf_bytes(b64_str)


class PdfViewerTab(QWidget):
    """Widget Tab per visualizzazione e annotazione PDF completa in cITA Studio."""

    def __init__(self, pdf_path: str = "", parent=None):
        super().__init__(parent)
        self.pdf_path = pdf_path
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

        self.web_view = QWebEngineView(self)
        self.layout.addWidget(self.web_view)

        # Setup WebChannel per il salvataggio nativo e la stampa
        self.channel = QWebChannel(self.web_view.page())
        self.bridge = PdfBridge(self)
        self.channel.registerObject("pyBridge", self.bridge)
        self.web_view.page().setWebChannel(self.channel)

        # Gestione richiesta di stampa dal browser
        self.web_view.page().printRequested.connect(self._on_print_requested)

        # Inizializza visualizzatore
        self.web_view.setHtml(PDF_STUDIO_HTML, QUrl("https://cita-pdf-studio/"))
        self.web_view.loadFinished.connect(self._on_loaded)

    def _on_loaded(self, ok: bool):
        if ok and self.pdf_path and os.path.exists(self.pdf_path):
            self.load_file(self.pdf_path)

    def _on_print_requested(self):
        self.web_view.page().runJavaScript("printPdf();")

    def load_file(self, file_path: str):
        self.pdf_path = file_path
        with open(file_path, "rb") as f:
            b64_content = base64.b64encode(f.read()).decode("ascii")
        self.web_view.page().runJavaScript(f"loadPdfFromBase64('{b64_content}');")

    def salva_pdf_bytes(self, b64_str: str):
        """Salva il PDF modificato chiedendo all'utente dove salvarlo, proponendo la cartella di origine."""
        try:
            pdf_bytes = base64.b64decode(b64_str)
            
            if self.pdf_path and os.path.exists(self.pdf_path):
                src_dir = os.path.dirname(self.pdf_path)
                stem = Path(self.pdf_path).stem
                default_name = os.path.join(src_dir, f"{stem}_modificato.pdf")
            else:
                default_name = os.path.expanduser("~/documento_modificato.pdf")

            out_path, _ = QFileDialog.getSaveFileName(
                self,
                "Salva documento PDF modificato",
                default_name,
                "File PDF (*.pdf)"
            )
            if not out_path:
                return

            with open(out_path, "wb") as f:
                f.write(pdf_bytes)

            QMessageBox.information(
                self,
                "PDF Salvato",
                f"Il documento PDF modificato è stato salvato con successo in:\n{out_path}"
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Errore Salvataggio",
                f"Impossibile salvare il documento PDF:\n{e}"
            )

    def stampa_pdf_bytes(self, b64_str: str = ""):
        """Stampa il documento PDF (inclusi annotazioni e testi) aprendo la finestra di dialogo nativa di stampa."""
        import tempfile
        from PySide6.QtPdf import QPdfDocument
        from PySide6.QtPrintSupport import QPrinter, QPrintDialog
        from PySide6.QtGui import QPainter
        from PySide6.QtCore import QSize

        temp_path = None
        try:
            # 1. Recupera o crea i bytes del PDF
            if b64_str:
                pdf_bytes = base64.b64decode(b64_str)
            elif self.pdf_path and os.path.exists(self.pdf_path):
                with open(self.pdf_path, "rb") as f:
                    pdf_bytes = f.read()
            else:
                QMessageBox.warning(self, "Stampa PDF", "Nessun documento disponibile per la stampa.")
                return

            # 2. Salva in un file temporaneo per il rendering tramite QPdfDocument
            temp_fd, temp_path = tempfile.mkstemp(suffix=".pdf")
            with os.fdopen(temp_fd, "wb") as f:
                f.write(pdf_bytes)

            doc = QPdfDocument(self)
            doc.load(temp_path)
            page_count = doc.pageCount()
            if page_count <= 0:
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass
                QMessageBox.warning(self, "Stampa PDF", "Il file PDF risulta vuoto o non leggibile.")
                return

            # 3. Configura QPrinter e apre QPrintDialog
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            doc_title = Path(self.pdf_path).name if self.pdf_path else "Documento_cITA"
            printer.setDocName(doc_title)

            dialog = QPrintDialog(printer, self)
            dialog.setWindowTitle(f"Stampa: {doc_title}")
            dialog.setMinMax(1, page_count)
            dialog.setOption(QPrintDialog.PrintDialogOption.PrintToFile, True)
            dialog.setOption(QPrintDialog.PrintDialogOption.PrintPageRange, True)

            if dialog.exec() != QPrintDialog.DialogCode.Accepted:
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass
                return

            # 4. Determina intervallo pagine da stampare
            from_page = 1
            to_page = page_count
            if printer.printRange() == QPrinter.PrintRange.PageRange:
                from_page = max(1, printer.fromPage())
                to_page = min(page_count, printer.toPage())

            # 5. Stampa le pagine
            painter = QPainter(printer)
            for p_idx in range(from_page - 1, to_page):
                if p_idx > (from_page - 1):
                    printer.newPage()

                page_rect = printer.pageLayout().paintRectPixels(printer.resolution())
                render_size = QSize(int(page_rect.width()), int(page_rect.height()))
                img = doc.render(p_idx, render_size)
                painter.drawImage(page_rect, img)

            painter.end()

        except Exception as e:
            QMessageBox.critical(
                self,
                "Errore Stampa PDF",
                f"Si è verificato un errore durante la stampa del documento:\n{e}"
            )
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

