// 语音输入：浏览器录音 / 上传 → 16k 单声道 WAV → POST /api/transcribe。
// 交互沿用 Gradio 版：识别结果先进预编辑框，用户确认后再放进对话输入框（不自动发送）。
import { esc } from "./dom.js";
import { ic } from "./icons.js";
import { openSheet, closeSheet } from "./ui/sheet.js";
import { go } from "./router.js";
import { showToast } from "./ui/toast.js";
import { Api } from "./api.js";
import { cache } from "./data.js";

const MAX_SECONDS = 60;
const MAX_BYTES = 10 * 1024 * 1024;

function asrState() {
  const asr = (cache.boot && cache.boot.asr) || {};
  return { enabled: Boolean(asr.enabled), detail: asr.detail || "" };
}

function sheetHtml() {
  const { enabled, detail } = asrState();
  const status = enabled
    ? "语音服务已就绪。尽量靠近麦克风说完整短句，核对产品、市场和数字后再发送。"
    : (detail || "当前环境语音服务未启用；可以继续使用文字。");
  return `
    <div class="sheet__grab"></div>
    <div class="sheet__body">
      <div class="sheet__top">
        <span class="sheet__lead" style="margin:0">语音输入</span>
        <button class="sheet__close" data-action="close-sheet" aria-label="关闭">${ic("close")}</button>
      </div>
      <h2>说完先确认，再发送</h2>
      <p class="sheet__lead">识别结果会先进预编辑框。核对产品名称、国家和数字无误后，再放进输入框发送。</p>
      <div class="sheet__status" id="voiceStatus" ${enabled ? "" : 'style="opacity:.75"'}>${ic("shield")}${esc(status)}</div>

      <div class="sheet__section">
        <h3>录音或上传</h3>
        <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
          <button class="btn" id="voiceRecord" type="button" ${enabled ? "" : "disabled"}>● 开始录音</button>
          <label class="btn" style="cursor:pointer;${enabled ? "" : "opacity:.5;pointer-events:none"}">
            上传音频
            <input id="voiceFile" type="file" accept="audio/*" style="display:none" ${enabled ? "" : "disabled"} />
          </label>
        </div>
        <p class="fine" style="margin-top:9px">最长 ${MAX_SECONDS} 秒、${MAX_BYTES / 1024 / 1024}MB；浏览器会先转成 16k 单声道 WAV 再上传。</p>
      </div>

      <div class="sheet__section">
        <h3>预编辑 · 未提交</h3>
        <textarea id="voiceText" rows="4" maxlength="6000"
          style="width:100%;box-sizing:border-box;border:1px solid var(--line,#d9ded8);border-radius:10px;padding:10px 11px;font:inherit;line-height:1.7;background:var(--paper,#fafaf7);color:inherit;resize:vertical"
          placeholder="转写结果会出现在这里，可以直接改字"></textarea>
        <div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap">
          <button class="btn btn--primary" id="voiceTranscribe" type="button" disabled>${ic("mic")}转写到输入框</button>
          <button class="btn" id="voiceUndo" type="button" disabled>撤销识别</button>
        </div>
      </div>

      <div class="sheet__actions">
        <button class="btn btn--primary btn--block" id="voiceSend" type="button">${ic("send")}把文字放进输入框</button>
      </div>
    </div>`;
}

async function toWav(blob) {
  const Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx) throw new Error("当前浏览器不支持音频处理，请改用 WAV 上传。");
  const context = new Ctx();
  let decoded;
  try {
    decoded = await context.decodeAudioData(await blob.arrayBuffer());
  } catch (error) {
    await context.close().catch(() => {});
    throw new Error("浏览器无法解码这段音频，请改用 WAV 文件上传。");
  }
  if (decoded.duration > MAX_SECONDS + 0.5) {
    await context.close().catch(() => {});
    throw new Error(`录音超过 ${MAX_SECONDS} 秒，请缩短后重试。`);
  }
  const rate = 16000;
  const frames = Math.max(1, Math.ceil(decoded.duration * rate));
  const offline = new OfflineAudioContext(1, frames, rate);
  const source = offline.createBufferSource();
  source.buffer = decoded;
  source.connect(offline.destination);
  source.start(0);
  const rendered = await offline.startRendering();
  await context.close().catch(() => {});

  const samples = rendered.getChannelData(0);
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const text = (offset, value) => {
    for (let i = 0; i < value.length; i += 1) view.setUint8(offset + i, value.charCodeAt(i));
  };
  text(0, "RIFF"); view.setUint32(4, 36 + samples.length * 2, true); text(8, "WAVE");
  text(12, "fmt "); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
  view.setUint16(22, 1, true); view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  text(36, "data"); view.setUint32(40, samples.length * 2, true);
  let offset = 44;
  for (let i = 0; i < samples.length; i += 1, offset += 2) {
    const value = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, value < 0 ? value * 0x8000 : value * 0x7fff, true);
  }
  return new Blob([buffer], { type: "audio/wav" });
}

export function openVoiceSheet() {
  openSheet(sheetHtml());
  const status = document.getElementById("voiceStatus");
  const fileInput = document.getElementById("voiceFile");
  const recordBtn = document.getElementById("voiceRecord");
  const transcribeBtn = document.getElementById("voiceTranscribe");
  const undoBtn = document.getElementById("voiceUndo");
  const sendBtn = document.getElementById("voiceSend");
  const textarea = document.getElementById("voiceText");
  if (!status || !textarea) return;

  const beforeText = (document.querySelector(".composer textarea") || {}).value || "";
  let audioBlob = null;
  let voiceText = "";
  let recorder = null;
  let chunks = [];
  let timer = null;
  let startedAt = 0;

  const setStatus = (message) => { status.innerHTML = `${ic("shield")}${esc(message)}`; };

  const refreshButtons = () => {
    transcribeBtn.disabled = !audioBlob || Boolean(transcribeBtn.dataset.busy);
    undoBtn.disabled = !voiceText;
  };

  const stopRecording = () => {
    if (recorder && recorder.state !== "inactive") recorder.stop();
    if (timer) { clearInterval(timer); timer = null; }
  };

  recordBtn.addEventListener("click", async () => {
    if (recorder && recorder.state === "recording") {
      stopRecording();
      return;
    }
    if (!navigator.mediaDevices || !window.MediaRecorder) {
      setStatus("当前浏览器不支持录音，请改用「上传音频」。");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mime = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"]
        .find((type) => MediaRecorder.isTypeSupported(type)) || "";
      chunks = [];
      recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      recorder.ondataavailable = (event) => { if (event.data && event.data.size) chunks.push(event.data); };
      recorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());
        recordBtn.textContent = "● 开始录音";
        if (!chunks.length) { setStatus("没有录到声音，请重试。"); return; }
        setStatus("正在转换音频…");
        try {
          audioBlob = await toWav(new Blob(chunks, { type: recorder.mimeType || "audio/webm" }));
          if (audioBlob.size > MAX_BYTES) throw new Error("录音超过 10MB，请缩短后重试。");
          const seconds = Math.round((Date.now() - startedAt) / 100) / 10;
          setStatus(`录音完成 · ${seconds} 秒。点「转写到输入框」继续。`);
          refreshButtons();
        } catch (error) {
          audioBlob = null;
          setStatus(error.message);
          refreshButtons();
        }
      };
      recorder.start();
      startedAt = Date.now();
      recordBtn.textContent = "■ 停止录音";
      setStatus("正在录音…再点一次停止。");
      timer = setInterval(() => {
        const seconds = (Date.now() - startedAt) / 1000;
        if (seconds >= MAX_SECONDS) {
          stopRecording();
          setStatus(`已达到 ${MAX_SECONDS} 秒上限，正在转换音频…`);
        } else {
          recordBtn.textContent = `■ 停止录音（${Math.floor(seconds)}s）`;
        }
      }, 250);
    } catch (error) {
      setStatus("没有取得麦克风权限。可以允许权限后重试，或改用「上传音频」。");
    }
  });

  fileInput.addEventListener("change", async () => {
    const file = fileInput.files && fileInput.files[0];
    if (!file) return;
    if (file.size > MAX_BYTES) { setStatus("音频超过 10MB，请换一个更短的文件。"); return; }
    setStatus("正在转换音频…");
    try {
      audioBlob = await toWav(file);
      if (audioBlob.size > MAX_BYTES) throw new Error("转换后的音频超过 10MB。");
      setStatus(`已选择：${file.name}。点「转写到输入框」继续。`);
      refreshButtons();
    } catch (error) {
      audioBlob = null;
      setStatus(error.message);
      refreshButtons();
    }
  });

  transcribeBtn.addEventListener("click", async () => {
    if (!audioBlob) { setStatus("请先录音或上传音频。"); return; }
    transcribeBtn.dataset.busy = "1";
    refreshButtons();
    setStatus("正在转写…");
    try {
      const result = await Api.transcribe(audioBlob, "voice.wav");
      voiceText = String(result.text || "").trim();
      textarea.value = voiceText;
      const meta = result.meta || {};
      const backend = { engine: "本地引擎", cloud: "云端" }[meta.backend] || "转写";
      setStatus(`预编辑 · 未提交｜${backend}${meta.seconds ? ` · ${meta.seconds}s` : ""} · ${voiceText.length} 字。确认后点下方按钮放进输入框。`);
      if (!voiceText) setStatus("没有识别到文字，请重录或直接输入。");
    } catch (error) {
      setStatus(error.message);
    } finally {
      delete transcribeBtn.dataset.busy;
      refreshButtons();
    }
  });

  undoBtn.addEventListener("click", () => {
    if (!voiceText) return;
    if (textarea.value.trim() !== voiceText.trim()) {
      setStatus("识别文字已被修改，撤销已失效；当前文字保留不动。");
      return;
    }
    textarea.value = beforeText;
    voiceText = "";
    setStatus("已撤销识别，恢复为识别前的文字。");
    refreshButtons();
  });

  sendBtn.addEventListener("click", () => {
    const text = textarea.value.trim();
    if (!text) { showToast("先转写或输入一段文字"); return; }
    closeSheet();
    go("assistant");
    window.setTimeout(() => {
      const composer = document.querySelector(".composer textarea");
      if (composer) {
        composer.value = text;
        composer.style.height = "auto";
        composer.style.height = Math.min(composer.scrollHeight, 116) + "px";
        composer.focus();
      }
      showToast("已放进输入框 · 核对后点发送");
    }, 60);
  });

  refreshButtons();
}
