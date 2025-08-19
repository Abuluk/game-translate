import os
from typing import Optional

from PySide6 import QtCore, QtWidgets
from dotenv import load_dotenv

from app.audio.device_enumeration import get_input_devices, get_output_devices, get_default_loopback_device, get_stereo_mix_devices
from app.audio.activity_probe import probe_speakers_activity
from app.workers.stream_workers import SystemStreamWorker, MicStreamWorker
from app.config.runtime_config import get_config, update_config, AppConfig, STTApiConfig, LocalSTTConfig, LocalTTSConfig
from app.utils.process_enum import list_processes
from app.config.persist import load_persisted_config, save_persisted_config
from app.ui.overlay import OverlayWindow
from app.ui.overlay_settings_dialog import OverlaySettingsDialog


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        load_dotenv(override=False)
        # Load persisted config and apply to runtime
        persisted = load_persisted_config()
        if persisted:
            update_config(persisted)
        self.setWindowTitle("游戏语音实时翻译")
        self.resize(920, 640)

        central = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(central)
        # Split top (config) and bottom (output/log) so bottom stays stable on mode changes
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self.top_panel = QtWidgets.QWidget(); self.top_layout = QtWidgets.QVBoxLayout(self.top_panel)
        self.bottom_panel = QtWidgets.QWidget(); self.bottom_layout = QtWidgets.QVBoxLayout(self.bottom_panel)
        self.splitter.addWidget(self.top_panel)
        self.splitter.addWidget(self.bottom_panel)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        layout.addWidget(self.splitter, 1)

        # Target language selector
        lang_layout = QtWidgets.QHBoxLayout()
        lang_layout.addWidget(QtWidgets.QLabel("目标语言:"))
        self.combo_lang = QtWidgets.QComboBox()
        self.combo_lang.addItems([
            "zh-CN", "en", "ja", "ko", "fr", "de", "es", "ru", "pt",
        ])
        # Restore target language from persisted config if available
        self.combo_lang.setCurrentText(get_config().target_language or os.getenv("APP_LANGUAGE_TARGET", "zh-CN"))
        lang_layout.addWidget(self.combo_lang, 1)

        self.top_layout.addLayout(lang_layout)

        # Devices
        device_group = QtWidgets.QGroupBox("设备设置")
        device_form = QtWidgets.QFormLayout(device_group)

        self.combo_mic = QtWidgets.QComboBox()
        self.combo_out = QtWidgets.QComboBox()
        self.combo_loop = QtWidgets.QComboBox()

        self.refresh_devices()

        device_form.addRow("麦克风输入:", self.combo_mic)
        device_form.addRow("TTS 输出设备:", self.combo_out)
        device_form.addRow("系统音频(Loopback):", self.combo_loop)
        self.top_layout.addWidget(device_group)
        # Subtitles only
        self.check_subtitles_only = QtWidgets.QCheckBox("翻译仅用于字幕（不使用麦克风与TTS回放）")
        self.check_subtitles_only.setChecked(get_config().subtitles_only)
        self.check_subtitles_only.toggled.connect(lambda _: self.update_tts_visibility())
        self.top_layout.addWidget(self.check_subtitles_only)

        # STT Provider settings
        stt_group = QtWidgets.QGroupBox("识别来源")
        stt_form = QtWidgets.QFormLayout(stt_group)
        self._stt_group = stt_group

        self.combo_stt_mode = QtWidgets.QComboBox()
        self.combo_stt_mode.addItems(["api", "local", "local-gguf"])
        self.combo_stt_mode.setCurrentText(get_config().stt_mode)
        self.combo_stt_mode.currentTextChanged.connect(self.update_stt_mode_visibility)
        # provider on same row as mode (visible for api)
        self.combo_provider = QtWidgets.QComboBox()
        self.combo_provider.addItems(["generic-ws", "baidu", "aliyun", "azure", "iflytek"])
        self.combo_provider.setCurrentText(get_config().stt_api.provider or "generic-ws")
        self.combo_provider.currentTextChanged.connect(self.update_provider_visibility)
        self.mode_provider_row = QtWidgets.QWidget()
        mp_hl = QtWidgets.QHBoxLayout(self.mode_provider_row)
        mp_hl.setContentsMargins(0, 0, 0, 0)
        mp_hl.setSpacing(12)
        mp_hl.addWidget(QtWidgets.QLabel("模式:"))
        mp_hl.addWidget(self.combo_stt_mode, 1)
        mp_hl.addWidget(QtWidgets.QLabel("提供商:"))
        mp_hl.addWidget(self.combo_provider, 1)
        stt_form.addRow(self.mode_provider_row)

        # API (WebSocket) settings panel
        self.api_panel = QtWidgets.QWidget()
        api_form = QtWidgets.QFormLayout(self.api_panel)

        # Compact row: model + from/to + sr + heartbeat + frame
        self.edit_stt_model = QtWidgets.QLineEdit(get_config().stt_api.model)
        langs = ["auto", "zh", "zh-CN", "en", "ja", "ko", "fr", "de", "es", "ru", "pt"]
        self.combo_from_lang = QtWidgets.QComboBox(); self.combo_from_lang.addItems(langs)
        self.combo_from_lang.setCurrentText(get_config().stt_api.from_lang or "auto")
        self.combo_to_lang = QtWidgets.QComboBox(); self.combo_to_lang.addItems(langs)
        self.combo_to_lang.setCurrentText(get_config().stt_api.to_lang or "zh")
        self.combo_sr = QtWidgets.QComboBox(); self.combo_sr.addItems(["8000", "16000", "44100"])
        self.combo_sr.setCurrentText(str(get_config().stt_api.sample_rate))
        self.spin_heartbeat = QtWidgets.QDoubleSpinBox(); self.spin_heartbeat.setRange(1.0, 60.0); self.spin_heartbeat.setSingleStep(0.5); self.spin_heartbeat.setValue(float(get_config().stt_api.heartbeat_interval_sec))
        self.spin_frame = QtWidgets.QSpinBox(); self.spin_frame.setRange(10, 100); self.spin_frame.setSingleStep(5); self.spin_frame.setValue(int(get_config().stt_api.frame_ms))
        # model width about 2x from combo
        try:
            from_w = self.combo_from_lang.sizeHint().width()
            self.edit_stt_model.setMaximumWidth(max(int(from_w * 2), 180))
        except Exception:
            self.edit_stt_model.setMaximumWidth(240)
        row_compact = QtWidgets.QWidget()
        rc_hl = QtWidgets.QHBoxLayout(row_compact)
        rc_hl.setContentsMargins(0, 0, 0, 0)
        rc_hl.setSpacing(12)
        rc_hl.addWidget(QtWidgets.QLabel("模型:")); rc_hl.addWidget(self.edit_stt_model, 2)
        rc_hl.addWidget(QtWidgets.QLabel("from:")); rc_hl.addWidget(self.combo_from_lang, 1)
        rc_hl.addWidget(QtWidgets.QLabel("to:")); rc_hl.addWidget(self.combo_to_lang, 1)
        rc_hl.addWidget(QtWidgets.QLabel("采样率:")); rc_hl.addWidget(self.combo_sr, 1)
        rc_hl.addWidget(QtWidgets.QLabel("心跳(s):")); rc_hl.addWidget(self.spin_heartbeat, 1)
        rc_hl.addWidget(QtWidgets.QLabel("帧长(ms):")); rc_hl.addWidget(self.spin_frame, 1)
        api_form.addRow(row_compact)

        # Generic WS credentials
        self.generic_panel = QtWidgets.QWidget()
        gen_form = QtWidgets.QFormLayout(self.generic_panel)
        self.edit_ws_url = QtWidgets.QLineEdit(get_config().stt_api.websocket_url)
        self.edit_ws_header = QtWidgets.QLineEdit(get_config().stt_api.auth_header)
        self.edit_ws_token = QtWidgets.QLineEdit(get_config().stt_api.auth_token)
        self.edit_ws_token.setEchoMode(QtWidgets.QLineEdit.Password)
        gen_form.addRow("WS URL:", self.edit_ws_url)
        # two-in-one row for header+token
        row_ht = QtWidgets.QWidget()
        ht_hl = QtWidgets.QHBoxLayout(row_ht)
        ht_hl.setContentsMargins(0, 0, 0, 0)
        ht_hl.setSpacing(12)
        ht_hl.addWidget(QtWidgets.QLabel("Auth Header:"))
        ht_hl.addWidget(self.edit_ws_header, 1)
        ht_hl.addWidget(QtWidgets.QLabel("Auth Token:"))
        ht_hl.addWidget(self.edit_ws_token, 1)
        gen_form.addRow(row_ht)
        api_form.addRow(self.generic_panel)

        # Baidu
        self.baidu_panel = QtWidgets.QWidget()
        bd_form = QtWidgets.QFormLayout(self.baidu_panel)
        self.edit_baidu_appid = QtWidgets.QLineEdit(get_config().stt_api.baidu_app_id)
        self.edit_baidu_api_key = QtWidgets.QLineEdit(get_config().stt_api.baidu_api_key)
        self.edit_baidu_secret_key = QtWidgets.QLineEdit(get_config().stt_api.baidu_secret_key)
        self.edit_baidu_api_key.setEchoMode(QtWidgets.QLineEdit.Password)
        self.edit_baidu_secret_key.setEchoMode(QtWidgets.QLineEdit.Password)
        # AppID + API Key in one row
        row_bk = QtWidgets.QWidget()
        bk_hl = QtWidgets.QHBoxLayout(row_bk)
        bk_hl.setContentsMargins(0, 0, 0, 0)
        bk_hl.setSpacing(12)
        bk_hl.addWidget(QtWidgets.QLabel("Baidu AppID:"))
        bk_hl.addWidget(self.edit_baidu_appid, 1)
        bk_hl.addWidget(QtWidgets.QLabel("API Key:"))
        bk_hl.addWidget(self.edit_baidu_api_key, 1)
        bd_form.addRow(row_bk)
        bd_form.addRow("Secret Key:", self.edit_baidu_secret_key)
        # Baidu optional
        self.check_baidu_return_tts = QtWidgets.QCheckBox("返回TTS音频")
        self.check_baidu_return_tts.setChecked(get_config().stt_api.baidu_return_target_tts)
        self.combo_baidu_tts_speaker = QtWidgets.QComboBox()
        self.combo_baidu_tts_speaker.addItems(["man", "woman"])  # 当前仅英语支持
        self.combo_baidu_tts_speaker.setCurrentText(get_config().stt_api.baidu_tts_speaker or "man")
        self.edit_baidu_user_sn = QtWidgets.QLineEdit(get_config().stt_api.baidu_user_sn)
        bd_form.addRow(self.check_baidu_return_tts)
        row_ts = QtWidgets.QWidget()
        ts_hl = QtWidgets.QHBoxLayout(row_ts)
        ts_hl.setContentsMargins(0, 0, 0, 0)
        ts_hl.setSpacing(12)
        ts_hl.addWidget(QtWidgets.QLabel("TTS Speaker:"))
        ts_hl.addWidget(self.combo_baidu_tts_speaker, 1)
        ts_hl.addWidget(QtWidgets.QLabel("User SN:"))
        ts_hl.addWidget(self.edit_baidu_user_sn, 1)
        bd_form.addRow(row_ts)
        api_form.addRow(self.baidu_panel)

        # Aliyun
        self.aliyun_panel = QtWidgets.QWidget()
        ali_form = QtWidgets.QFormLayout(self.aliyun_panel)
        self.edit_ali_ak = QtWidgets.QLineEdit(get_config().stt_api.aliyun_access_key_id)
        self.edit_ali_sk = QtWidgets.QLineEdit(get_config().stt_api.aliyun_access_key_secret)
        self.edit_ali_app_key = QtWidgets.QLineEdit(get_config().stt_api.aliyun_app_key)
        self.edit_ali_endpoint = QtWidgets.QLineEdit(get_config().stt_api.aliyun_endpoint)
        self.edit_ali_sk.setEchoMode(QtWidgets.QLineEdit.Password)
        ali_form.addRow("AccessKeyId:", self.edit_ali_ak)
        ali_form.addRow("AccessKeySecret:", self.edit_ali_sk)
        ali_form.addRow("AppKey:", self.edit_ali_app_key)
        ali_form.addRow("Endpoint:", self.edit_ali_endpoint)
        api_form.addRow(self.aliyun_panel)

        # Azure
        self.azure_panel = QtWidgets.QWidget()
        az_form = QtWidgets.QFormLayout(self.azure_panel)
        self.edit_az_key = QtWidgets.QLineEdit(get_config().stt_api.azure_speech_key)
        self.edit_az_region = QtWidgets.QLineEdit(get_config().stt_api.azure_region)
        self.edit_az_endpoint = QtWidgets.QLineEdit(get_config().stt_api.azure_endpoint)
        self.edit_az_key.setEchoMode(QtWidgets.QLineEdit.Password)
        az_form.addRow("Speech Key:", self.edit_az_key)
        az_form.addRow("Region:", self.edit_az_region)
        az_form.addRow("Endpoint:", self.edit_az_endpoint)
        api_form.addRow(self.azure_panel)

        # iFlytek
        self.iflytek_panel = QtWidgets.QWidget()
        if_form = QtWidgets.QFormLayout(self.iflytek_panel)
        self.edit_if_appid = QtWidgets.QLineEdit(get_config().stt_api.iflytek_app_id)
        self.edit_if_api_key = QtWidgets.QLineEdit(get_config().stt_api.iflytek_api_key)
        self.edit_if_api_secret = QtWidgets.QLineEdit(get_config().stt_api.iflytek_api_secret)
        self.edit_if_api_key.setEchoMode(QtWidgets.QLineEdit.Password)
        self.edit_if_api_secret.setEchoMode(QtWidgets.QLineEdit.Password)
        if_form.addRow("AppID:", self.edit_if_appid)
        if_form.addRow("API Key:", self.edit_if_api_key)
        if_form.addRow("API Secret:", self.edit_if_api_secret)
        api_form.addRow(self.iflytek_panel)

        # OpenAI removed per Baidu API flow

        stt_form.addRow(self.api_panel)

        # Local settings panel (faster-whisper / CTranslate2)
        self.local_panel = QtWidgets.QWidget()
        local_form = QtWidgets.QFormLayout(self.local_panel)
        self.edit_local_model_path = QtWidgets.QLineEdit(get_config().local_stt.whisper_model)
        self.btn_browse_local = QtWidgets.QPushButton("浏览…")
        self.btn_browse_local.clicked.connect(self.on_browse_local_model)
        hl_local = QtWidgets.QHBoxLayout()
        hl_local.addWidget(self.edit_local_model_path, 1)
        hl_local.addWidget(self.btn_browse_local)
        local_form.addRow("本地 Whisper 模型目录:", self.wrap_layout(hl_local))

        # Local TTS model directory (shown only when not subtitles-only)
        try:
            init_tts_dir = get_config().local_tts.tts_model_dir  # type: ignore[union-attr]
        except Exception:
            init_tts_dir = ""
        self.edit_local_tts_model_path = QtWidgets.QLineEdit(init_tts_dir)
        self.btn_browse_local_tts = QtWidgets.QPushButton("浏览…")
        self.btn_browse_local_tts.clicked.connect(self.on_browse_local_tts_model)
        hl_local_tts = QtWidgets.QHBoxLayout()
        hl_local_tts.addWidget(self.edit_local_tts_model_path, 1)
        hl_local_tts.addWidget(self.btn_browse_local_tts)
        self.local_tts_row_widget = self.wrap_layout(hl_local_tts)
        local_form.addRow("语音合成模型目录:", self.local_tts_row_widget)

        # Local mode language controls (from/to)
        langs_local = ["auto", "zh", "zh-CN", "en", "ja", "ko", "fr", "de", "es", "ru", "pt"]
        self.combo_local_from_lang = QtWidgets.QComboBox(); self.combo_local_from_lang.addItems(langs_local)
        self.combo_local_from_lang.setCurrentText(get_config().stt_api.from_lang or "auto")
        self.combo_local_to_lang = QtWidgets.QComboBox(); self.combo_local_to_lang.addItems(langs_local)
        self.combo_local_to_lang.setCurrentText(get_config().stt_api.to_lang or "zh")
        row_local_langs = QtWidgets.QWidget()
        rll_hl = QtWidgets.QHBoxLayout(row_local_langs)
        rll_hl.setContentsMargins(0, 0, 0, 0)
        rll_hl.setSpacing(12)
        rll_hl.addWidget(QtWidgets.QLabel("from:"))
        rll_hl.addWidget(self.combo_local_from_lang, 1)
        rll_hl.addWidget(QtWidgets.QLabel("to:"))
        rll_hl.addWidget(self.combo_local_to_lang, 1)
        local_form.addRow("语言(本地):", row_local_langs)

        # Local VAD tuning controls
        self.spin_vad_energy = QtWidgets.QSpinBox(); self.spin_vad_energy.setRange(1, 100000); self.spin_vad_energy.setValue(int(get_config().local_vad.energy_threshold if hasattr(get_config(), 'local_vad') else 500))
        self.spin_vad_silence = QtWidgets.QSpinBox(); self.spin_vad_silence.setRange(1, 200); self.spin_vad_silence.setValue(int(get_config().local_vad.silence_frames if hasattr(get_config(), 'local_vad') else 10))
        self.spin_vad_max_ms = QtWidgets.QSpinBox(); self.spin_vad_max_ms.setRange(500, 30000); self.spin_vad_max_ms.setSingleStep(500); self.spin_vad_max_ms.setValue(int(get_config().local_vad.max_segment_ms if hasattr(get_config(), 'local_vad') else 6000))
        self.spin_vad_alpha = QtWidgets.QDoubleSpinBox(); self.spin_vad_alpha.setRange(0.0, 1.0); self.spin_vad_alpha.setSingleStep(0.01); self.spin_vad_alpha.setValue(float(get_config().local_vad.noise_alpha if hasattr(get_config(), 'local_vad') else 0.05))
        self.spin_vad_mult = QtWidgets.QDoubleSpinBox(); self.spin_vad_mult.setRange(0.1, 10.0); self.spin_vad_mult.setSingleStep(0.1); self.spin_vad_mult.setValue(float(get_config().local_vad.noise_multiplier if hasattr(get_config(), 'local_vad') else 2.0))
        vad_grid = QtWidgets.QGridLayout();
        vad_grid.addWidget(QtWidgets.QLabel("能量阈值"), 0, 0); vad_grid.addWidget(self.spin_vad_energy, 0, 1)
        vad_grid.addWidget(QtWidgets.QLabel("静音帧数"), 0, 2); vad_grid.addWidget(self.spin_vad_silence, 0, 3)
        vad_grid.addWidget(QtWidgets.QLabel("最大分段ms"), 1, 0); vad_grid.addWidget(self.spin_vad_max_ms, 1, 1)
        vad_grid.addWidget(QtWidgets.QLabel("噪声平滑α"), 1, 2); vad_grid.addWidget(self.spin_vad_alpha, 1, 3)
        vad_grid.addWidget(QtWidgets.QLabel("阈值倍率x"), 2, 0); vad_grid.addWidget(self.spin_vad_mult, 2, 1)
        local_form.addRow("本地VAD参数:", self.wrap_layout(vad_grid))

        # Local realtime preview toggle/interval
        self.check_vad_preview = QtWidgets.QCheckBox("分段实时预览")
        try:
            self.check_vad_preview.setChecked(bool(get_config().local_vad.preview_enabled))
        except Exception:
            self.check_vad_preview.setChecked(False)
        self.spin_preview_ms = QtWidgets.QSpinBox(); self.spin_preview_ms.setRange(200, 5000); self.spin_preview_ms.setSingleStep(100)
        try:
            self.spin_preview_ms.setValue(int(get_config().local_vad.preview_interval_ms))
        except Exception:
            self.spin_preview_ms.setValue(800)
        row_prev = QtWidgets.QHBoxLayout(); row_prev.addWidget(self.check_vad_preview); row_prev.addSpacing(12); row_prev.addWidget(QtWidgets.QLabel("间隔ms")); row_prev.addWidget(self.spin_preview_ms)
        local_form.addRow(self.wrap_layout(row_prev))

        # Local GGUF (whisper.cpp) settings panel
        self.local_gguf_panel = QtWidgets.QWidget()
        gguf_form = QtWidgets.QFormLayout(self.local_gguf_panel)
        self.edit_wcpp_exe = QtWidgets.QLineEdit(get_config().local_gguf.whisper_cpp_exe)
        self.btn_browse_wcpp_exe = QtWidgets.QPushButton("浏览…")
        self.btn_browse_wcpp_exe.clicked.connect(self.on_browse_wcpp_exe)
        row_exe = QtWidgets.QHBoxLayout(); row_exe.addWidget(self.edit_wcpp_exe, 1); row_exe.addWidget(self.btn_browse_wcpp_exe)
        gguf_form.addRow("whisper.cpp 可执行文件:", self.wrap_layout(row_exe))
        self.edit_wcpp_model = QtWidgets.QLineEdit(get_config().local_gguf.whisper_cpp_model)
        self.btn_browse_wcpp_model = QtWidgets.QPushButton("浏览…")
        self.btn_browse_wcpp_model.clicked.connect(self.on_browse_wcpp_model)
        row_model = QtWidgets.QHBoxLayout(); row_model.addWidget(self.edit_wcpp_model, 1); row_model.addWidget(self.btn_browse_wcpp_model)
        gguf_form.addRow("GGUF 模型路径:", self.wrap_layout(row_model))
        # （移除提示）

        stt_form.addRow(self.local_panel)
        stt_form.addRow(self.local_gguf_panel)

        btn_save_cfg = QtWidgets.QPushButton("应用配置")
        btn_save_cfg.clicked.connect(self.on_apply_config)
        stt_form.addRow(btn_save_cfg)

        self.top_layout.addWidget(stt_group)
        # Set initial visibility
        self.update_stt_mode_visibility(self.combo_stt_mode.currentText())
        self.update_provider_visibility(self.combo_provider.currentText())
        self.update_tts_visibility()
        

        # Target game section
        game_group = QtWidgets.QGroupBox("针对某个游戏（可选）")
        game_form = QtWidgets.QFormLayout(game_group)

        self.combo_game = QtWidgets.QComboBox()
        self.btn_refresh_games = QtWidgets.QPushButton("刷新进程")
        self.btn_refresh_games.clicked.connect(self.on_refresh_games)
        self.on_refresh_games()

        hl = QtWidgets.QHBoxLayout()
        hl.addWidget(self.combo_game, 1)
        hl.addWidget(self.btn_refresh_games)

        self.check_enforce = QtWidgets.QCheckBox("提醒我为该游戏做设备路由（虚拟声卡/混音器）")
        self.check_enforce.setChecked(get_config().enforce_routing)

        game_form.addRow("游戏进程:", hl)
        game_form.addRow(self.check_enforce)

        self.top_layout.addWidget(game_group)

        # Overlay settings button
        self.btn_overlay_settings = QtWidgets.QPushButton("字幕设置…")
        self.btn_overlay_settings.clicked.connect(self.on_open_overlay_settings)
        self.top_layout.addWidget(self.btn_overlay_settings)

        # Buttons
        btn_layout = QtWidgets.QHBoxLayout()
        self.btn_sys_start = QtWidgets.QPushButton("开始（系统翻译）")
        self.btn_sys_stop = QtWidgets.QPushButton("停止（系统翻译）")
        self.btn_probe = QtWidgets.QPushButton("检测播放设备活动")
        self.btn_mic_start = QtWidgets.QPushButton("开始（麦克风→TTS）")
        self.btn_mic_stop = QtWidgets.QPushButton("停止（麦克风→TTS）")
        btn_layout.addWidget(self.btn_sys_start)
        btn_layout.addWidget(self.btn_sys_stop)
        btn_layout.addWidget(self.btn_probe)
        btn_layout.addSpacing(20)
        btn_layout.addWidget(self.btn_mic_start)
        btn_layout.addWidget(self.btn_mic_stop)
        self.top_layout.addLayout(btn_layout)

        # Transcript view
        self.text_view = QtWidgets.QPlainTextEdit()
        self.text_view.setReadOnly(True)
        self.bottom_layout.addWidget(self.text_view, 1)

        # Connection event log
        self.event_log = QtWidgets.QPlainTextEdit()
        self.event_log.setReadOnly(True)
        self.event_log.setMaximumHeight(120)
        self.event_log.setPlaceholderText("连接事件日志…")
        self.bottom_layout.addWidget(self.event_log)

        # Footer
        self.status = QtWidgets.QStatusBar()
        self.setStatusBar(self.status)

        self.setCentralWidget(central)

        # Workers
        self.system_worker: Optional[SystemStreamWorker] = None
        self.mic_worker: Optional[MicStreamWorker] = None
        self.overlay = OverlayWindow()
        self.overlay.hide()

        # Signals
        self.btn_sys_start.clicked.connect(self.on_sys_start)
        self.btn_sys_stop.clicked.connect(self.on_sys_stop)
        self.btn_probe.clicked.connect(self.on_probe_activity)
        self.btn_mic_start.clicked.connect(self.on_mic_start)
        self.btn_mic_stop.clicked.connect(self.on_mic_stop)
        # When closing, save config
        self.destroyed.connect(self.on_close)

    def refresh_devices(self) -> None:
        self.combo_mic.clear()
        self.combo_out.clear()
        self.combo_loop.clear()

        inputs = get_input_devices()
        outputs = get_output_devices()
        loopback = get_default_loopback_device()
        stereo_mix = get_stereo_mix_devices()

        for d in inputs:
            self.combo_mic.addItem(d.name, d.index)
        for d in outputs:
            self.combo_out.addItem(d.name, d.index)
        # First: outputs (prefer WASAPI; also include WDM-KS/MME/DirectSound)
        for d in outputs:
            label = d.name
            if d.hostapi_name:
                label += f" [{d.hostapi_name}]"
            self.combo_loop.addItem(label, ("output", d.index))
        # Then: Stereo Mix style inputs
        if stereo_mix:
            self.combo_loop.addItem("—— 立体声混音（输入） ——", None)
            for d in stereo_mix:
                label = d.name
                if d.hostapi_name:
                    label += f" [{d.hostapi_name}]"
                self.combo_loop.addItem(label, ("input", d.index))

        # Restore previously selected devices if persisted
        cfg = get_config()
        if cfg.loop_device_index is not None:
            want = (cfg.loop_device_kind or "output", cfg.loop_device_index)
            idx = self.combo_loop.findData(want)
            if idx >= 0:
                self.combo_loop.setCurrentIndex(idx)
        elif loopback is not None:
            idx = self.combo_loop.findData(("output", loopback.index))
            if idx >= 0:
                self.combo_loop.setCurrentIndex(idx)

        if cfg.mic_device_index is not None:
            idx = self.combo_mic.findData(cfg.mic_device_index)
            if idx >= 0:
                self.combo_mic.setCurrentIndex(idx)
        if cfg.tts_output_device_index is not None:
            idx = self.combo_out.findData(cfg.tts_output_device_index)
            if idx >= 0:
                self.combo_out.setCurrentIndex(idx)
        # Emit basic device info
        try:
            import sounddevice as sd
            sel = self.combo_loop.currentData()
            dev_index = sel[1] if isinstance(sel, tuple) else sel
            info = sd.query_devices(dev_index)
            hostapi = sd.query_hostapis(info.get('hostapi'))
            self.append_text(
                f"当前Loopback设备: {info.get('name')} [{hostapi.get('name')}] | out_channels={info.get('max_output_channels')} in_channels={info.get('max_input_channels')}"
            )
            if hostapi and 'wasapi' not in str(hostapi.get('name', '')).lower():
                self.append_text("提示：首选选择带 [WASAPI] 的输出设备以启用系统回环捕获；或在声音设置中启用 '立体声混音' 作为输入设备。")
        except Exception:
            pass

    def append_text(self, text: str) -> None:
        self.text_view.appendPlainText(text)
        # Also mirror to overlay (last non-empty)
        t = text.strip()
        if t:
            self.overlay.show_text(t)

    def append_event(self, text: str) -> None:
        self.event_log.appendPlainText(text)

    def on_sys_start(self) -> None:
        self.on_sys_stop()
        target_lang = self.combo_lang.currentText()
        loop_idx = self.combo_loop.currentData()
        tts_out_idx = None if self.check_subtitles_only.isChecked() else self.combo_out.currentData()
        self.system_worker = SystemStreamWorker(loop_idx, target_lang, tts_out_idx)
        self.system_worker.message.connect(self.append_text)
        self.system_worker.event.connect(self.append_event)
        self.system_worker.status.connect(self.status.showMessage)
        self.system_worker.status.connect(self.append_text)
        self.system_worker.start()

    def on_sys_stop(self) -> None:
        if self.system_worker:
            self.system_worker.stop()
            self.system_worker = None
        self.overlay.clear_text()

    def on_mic_start(self) -> None:
        self.on_mic_stop()
        target_lang = self.combo_lang.currentText()
        mic_idx = self.combo_mic.currentData()
        out_idx = self.combo_out.currentData()
        self.mic_worker = MicStreamWorker(mic_idx, out_idx, target_lang)
        self.mic_worker.message.connect(self.append_text)
        self.mic_worker.event.connect(self.append_event)
        self.mic_worker.status.connect(self.status.showMessage)
        self.mic_worker.status.connect(self.append_text)
        self.mic_worker.start()

    def on_mic_stop(self) -> None:
        if self.mic_worker:
            self.mic_worker.stop()
            self.mic_worker = None

    def on_apply_config(self) -> None:
        cfg = get_config()
        # Select language values depending on mode
        mode_now = self.combo_stt_mode.currentText()
        from_lang_val = (self.combo_from_lang.currentText().strip() if mode_now == "api" else self.combo_local_from_lang.currentText().strip()) or "auto"
        to_lang_val = (self.combo_to_lang.currentText().strip() if mode_now == "api" else self.combo_local_to_lang.currentText().strip()) or "zh"
        # Local model path and quick validation (avoid whisper.cpp gguf models)
        local_model_val = self.edit_local_model_path.text().strip() or cfg.local_stt.whisper_model
        if mode_now == "local":
            try:
                import os as _os
                if local_model_val.lower().endswith(".gguf") or (_os.path.isfile(local_model_val) and local_model_val.lower().endswith(".gguf")):
                    self.status.showMessage("本地模型不支持 .gguf (whisper.cpp)。请选择 faster-whisper/CTranslate2 模型目录。", 5000)
                    return
                if _os.path.isdir(local_model_val):
                    for name in [".gguf", ".bin.gguf"]:
                        # heuristic: prevent dirs containing gguf
                        import glob as _glob
                        if any(p.lower().endswith(".gguf") for p in _glob.glob(_os.path.join(local_model_val, "**", "*.gguf"), recursive=True)):
                            self.status.showMessage("检测到 .gguf 文件。请改用 CTranslate2 转换后的 Whisper 模型目录。", 5000)
                            return
            except Exception:
                pass
        # whisper.cpp paths
        wcpp_exe_val = self.edit_wcpp_exe.text().strip() or cfg.local_gguf.whisper_cpp_exe
        wcpp_model_val = self.edit_wcpp_model.text().strip() or cfg.local_gguf.whisper_cpp_model
        # basic validate when choosing local-gguf
        if mode_now == "local-gguf":
            import os as _os
            if not (_os.path.isfile(wcpp_exe_val) and _os.path.isfile(wcpp_model_val)):
                self.status.showMessage("请正确选择 whisper.cpp 可执行文件与 GGUF 模型路径", 5000)
                return
        new_cfg = AppConfig(
            stt_mode=mode_now,
            stt_api=STTApiConfig(
                websocket_url=self.edit_ws_url.text().strip(),
                auth_header=self.edit_ws_header.text().strip() or "Authorization",
                auth_token=self.edit_ws_token.text().strip(),
                provider=self.combo_provider.currentText(),
                model=self.edit_stt_model.text().strip(),
                sample_rate=int(self.combo_sr.currentText()),
                from_lang=from_lang_val,
                to_lang=to_lang_val,
                heartbeat_interval_sec=float(self.spin_heartbeat.value()),
                frame_ms=int(self.spin_frame.value()),
                baidu_app_id=self.edit_baidu_appid.text().strip(),
                baidu_api_key=self.edit_baidu_api_key.text().strip(),
                baidu_secret_key=self.edit_baidu_secret_key.text().strip(),
                baidu_return_target_tts=self.check_baidu_return_tts.isChecked(),
                baidu_tts_speaker=self.combo_baidu_tts_speaker.currentText(),
                baidu_user_sn=self.edit_baidu_user_sn.text().strip(),
                aliyun_access_key_id=self.edit_ali_ak.text().strip(),
                aliyun_access_key_secret=self.edit_ali_sk.text().strip(),
                aliyun_app_key=self.edit_ali_app_key.text().strip(),
                aliyun_endpoint=self.edit_ali_endpoint.text().strip(),
                azure_speech_key=self.edit_az_key.text().strip(),
                azure_region=self.edit_az_region.text().strip(),
                azure_endpoint=self.edit_az_endpoint.text().strip(),
                iflytek_app_id=self.edit_if_appid.text().strip(),
                iflytek_api_key=self.edit_if_api_key.text().strip(),
                iflytek_api_secret=self.edit_if_api_secret.text().strip(),
            ),
            # OpenAI removed
            local_stt=LocalSTTConfig(
                whisper_model=local_model_val,
            ),
            local_tts=(get_config().local_tts.__class__(  # type: ignore[union-attr]
                tts_model_dir=self.edit_local_tts_model_path.text().strip(),
            ) if hasattr(get_config(), 'local_tts') and get_config().local_tts is not None else LocalTTSConfig(
                tts_model_dir=self.edit_local_tts_model_path.text().strip(),
            )),
            local_vad=get_config().local_vad.__class__(
                energy_threshold=int(self.spin_vad_energy.value()),
                silence_frames=int(self.spin_vad_silence.value()),
                max_segment_ms=int(self.spin_vad_max_ms.value()),
                noise_alpha=float(self.spin_vad_alpha.value()),
                noise_multiplier=float(self.spin_vad_mult.value()),
                preview_enabled=bool(self.check_vad_preview.isChecked()),
                preview_interval_ms=int(self.spin_preview_ms.value()),
            ),
            local_gguf=get_config().local_gguf.__class__(
                whisper_cpp_exe=wcpp_exe_val,
                whisper_cpp_model=wcpp_model_val,
            ),
            target_game_process=self.combo_game.currentData() or "",
            enforce_routing=self.check_enforce.isChecked(),
            subtitles_only=self.check_subtitles_only.isChecked(),
            target_language=self.combo_lang.currentText(),
            mic_device_index=self.combo_mic.currentData(),
            tts_output_device_index=self.combo_out.currentData(),
            loop_device_kind=(self.combo_loop.currentData()[0] if isinstance(self.combo_loop.currentData(), tuple) else "output"),
            loop_device_index=(self.combo_loop.currentData()[1] if isinstance(self.combo_loop.currentData(), tuple) else self.combo_loop.currentData()),
            # Keep existing overlay settings; they are edited via the overlay settings dialog
            overlay=get_config().overlay,
        )
        update_config(new_cfg)
        save_persisted_config(new_cfg)
        self.status.showMessage("配置已应用", 3000)

    def on_open_overlay_settings(self) -> None:
        cfg_ov = get_config().overlay
        dlg = OverlaySettingsDialog(
            font_size=int(cfg_ov.font_size),
            color_hex=cfg_ov.color_hex,
            bg_opacity=float(cfg_ov.bg_opacity),
            x_pct=float(cfg_ov.x_pct),
            y_pct=float(cfg_ov.y_pct),
            width_pct=float(cfg_ov.width_pct),
            height_pct=float(cfg_ov.height_pct),
            parent=self,
        )
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            vals = dlg.values()
            cfg = get_config()
            cfg.overlay.font_size = vals["font_size"]
            cfg.overlay.color_hex = vals["color_hex"]
            cfg.overlay.bg_opacity = vals["bg_opacity"]
            cfg.overlay.x_pct = vals["x_pct"]
            cfg.overlay.y_pct = vals["y_pct"]
            cfg.overlay.width_pct = vals["width_pct"]
            cfg.overlay.height_pct = vals["height_pct"]
            save_persisted_config(cfg)
            self.overlay.apply_config()

    def on_refresh_games(self) -> None:
        self.combo_game.clear()
        self.combo_game.addItem("（不指定）", "")
        try:
            for p in list_processes(limit=200):
                label = f"{p['name']} (pid {p['pid']})"
                self.combo_game.addItem(label, p["name"])
        except Exception:
            pass

    def on_probe_activity(self) -> None:
        self.append_text("开始检测播放设备活动…")
        results = probe_speakers_activity(duration_sec=0.5, sample_rate=44100)
        if not results:
            self.append_text("未检测到活动的播放设备。")
            return
        for r in results[:8]:
            self.append_text(f"设备活动: {r['name']} | RMS={r['rms']:.5f} | channels={r['channels']}")
        self.append_text("检测完成。若某设备 RMS 明显较高，优先选择该设备作为 Loopback。")

    def on_close(self) -> None:
        # Persist current UI config on close
        cfg = get_config()
        save_persisted_config(cfg)

    # Helpers
    def wrap_layout(self, layout: QtWidgets.QLayout) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        w.setLayout(layout)
        return w

    def on_browse_local_model(self) -> None:
        directory = QtWidgets.QFileDialog.getExistingDirectory(self, "选择本地 Whisper 模型目录")
        if directory:
            self.edit_local_model_path.setText(directory)

    def on_browse_wcpp_exe(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "选择 whisper.cpp 可执行文件", "", "Executables (*.exe);;All Files (*)")
        if path:
            self.edit_wcpp_exe.setText(path)

    def on_browse_wcpp_model(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "选择 GGUF 模型文件", "", "GGUF (*.gguf);;All Files (*)")
        if path:
            self.edit_wcpp_model.setText(path)

    def on_browse_local_tts_model(self) -> None:
        directory = QtWidgets.QFileDialog.getExistingDirectory(self, "选择本地 语音合成 模型目录")
        if directory:
            self.edit_local_tts_model_path.setText(directory)

    def update_stt_mode_visibility(self, mode: str) -> None:
        is_api = (mode == "api")
        try:
            self.mode_provider_row.setVisible(True)
            self.combo_provider.setVisible(is_api)
        except Exception:
            pass
        self.api_panel.setVisible(is_api)
        self.local_panel.setVisible(mode == "local")
        self.local_gguf_panel.setVisible(mode == "local-gguf")
        

    def update_provider_visibility(self, provider: str) -> None:
        # Always show generic panel (WS URL/Auth/模型/采样率)
        self.generic_panel.setVisible(True)
        # Toggle only provider-specific panels
        for w in [self.baidu_panel, self.aliyun_panel, self.azure_panel, self.iflytek_panel]:
            w.setVisible(False)
        if provider == "baidu":
            self.baidu_panel.setVisible(True)
        elif provider == "aliyun":
            self.aliyun_panel.setVisible(True)
        elif provider == "azure":
            self.azure_panel.setVisible(True)
        elif provider == "iflytek":
            self.iflytek_panel.setVisible(True)

    def update_tts_visibility(self) -> None:
        try:
            show = not bool(self.check_subtitles_only.isChecked())
            self.local_tts_row_widget.setVisible(show)
        except Exception:
            pass
        

    


