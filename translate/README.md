## 游戏语音实时翻译（Windows 桌面应用）

一个在 Windows 上运行的实时语音翻译工具：
- 捕获游戏/系统声音做实时翻译（显示字幕）
- 捕获麦克风做实时翻译，并将合成后的目标语言语音输出到选定设备（建议为虚拟麦克风，如 VB-CABLE），供游戏作为麦克风输入使用
- 自动识别语种，翻译到用户选择的目标语言

### 功能概览
- **系统/游戏音频翻译**：通过 WASAPI Loopback 捕获系统输出，WebSocket 真流或本地 VAD+Whisper 分段翻译，显示字幕。
- **麦克风翻译+回放**：捕获麦克风，WebSocket 真流或本地 VAD+Whisper 翻译，使用 TTS 合成并回放到指定输出设备（如虚拟麦克风），可在游戏中选择该设备作为麦克风。
- **可插拔 Provider**：
  - STT：WebSocket 真流（可在界面配置 URL/鉴权），或本地 faster-whisper（含 VAD 实时切分）
  - 翻译/TTS：OpenAI（可在界面输入 API Key 和模型）
  - 目标游戏：界面可选择进程名，并勾选“提醒我为该游戏做设备路由”。

### 环境要求
- Windows 10/11
- Python 3.10+（64-bit）
- 建议安装一个虚拟音频设备作为“虚拟麦克风”，例如：`VB-Audio Virtual Cable (VB-CABLE)`
  - 安装后在游戏中将“麦克风输入设备”设置为 VB-CABLE 的输入端
  - 在本应用中将“输出设备（TTS 回放）”设置为 VB-CABLE 的输出端

### 快速开始
1) 克隆/定位到本项目目录 `translate/`

2) 创建并填充环境变量
```
cp .env.example .env
# 编辑 .env，填入 OpenAI Key
```

3) 安装依赖（本地安装，无需虚拟环境）
```
# Windows（推荐）
py -3 -m pip install --user -r requirements.txt

# 或通用方式
python -m pip install --user -r requirements.txt
```

4) 运行应用
```
python -m app.main
```

### 使用说明
- 打开应用后：
  - 选择“目标语言”（例如 `zh-CN`、`en`、`ja` ...）
  - 可选择“系统音频（游戏）”捕获的设备（一般为默认输出设备的 loopback；已自动处理）
  - 选择“麦克风输入设备”和“TTS 输出设备”（TTS 输出设备请选择虚拟麦克风）
  - 在“针对某个游戏”中选择你的游戏进程（如 `game.exe`），并按提示进行 Windows 路由（音量混合器/虚拟音频）
  - 点击“开始（系统翻译）”显示游戏声音的字幕
  - 点击“开始（麦克风翻译→TTS）”将你的话翻译并合成为目标语言，输出到选定设备

### 配置（可在界面中直接设置）
- **识别模式**：`api`（WebSocket 真流）或 `local`（本地 faster-whisper）
- **WebSocket STT**：`WS URL`、`Auth Header`、`Auth Token`
- **OpenAI**：`API Key`、`STT 模型`、`TTS 模型`、`翻译模型`
- **本地模型**：`Whisper 模型`（如 `base`/`small`）

注：已支持 WebSocket 真流；若后端遵循 `{type:start|audio|transcript|stop}` 简单协议即可直接接入。

### 常见问题
- 听不到 TTS 或游戏未收到麦克风：请确认
  - 安装并选择了虚拟音频设备
  - 游戏中将麦克风设为虚拟设备输入端
  - 本应用中 TTS 输出设备选择为虚拟设备输出端
- 捕获不到系统音频：
  - 检查 Windows 是否支持 WASAPI（Win10+ 一般支持）
  - 确保在播放设备上有声音输出

### 许可
本项目用于演示/集成目的，用户需自行遵守各 API 的使用条款。


