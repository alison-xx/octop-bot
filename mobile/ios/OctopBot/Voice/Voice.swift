import AVFoundation
import Observation
import Speech

/// Records a voice clip, then turns it into text: the backend's recognizer first, on-device otherwise.
@Observable
final class VoiceRecorder {
    private(set) var isRecording = false
    private(set) var level: Float = 0
    private var recorder: AVAudioRecorder?
    private var meter: Task<Void, Never>?
    private let file = FileManager.default.temporaryDirectory.appendingPathComponent("octop-voice.m4a")

    /// Why the last attempt to record failed, for the UI.
    private(set) var failure: String?

    func start() async {
        guard !isRecording else { return }
        failure = nil
        Speaker.shared.stop()
        guard await AVAudioApplication.requestRecordPermission() else {
            failure = L("voice.micDenied")
            return
        }
        // Session changes can block; keep them off the main thread.
        let ready = await Task.detached(priority: .userInitiated) { () -> Bool in
            let session = AVAudioSession.sharedInstance()
            do {
                try session.setCategory(.playAndRecord, mode: .spokenAudio, options: [.defaultToSpeaker, .allowBluetoothHFP])
                try session.setActive(true)
                return session.isInputAvailable
            } catch {
                return false
            }
        }.value
        guard ready, let recorder = try? AVAudioRecorder(url: file, settings: [
            AVFormatIDKey: kAudioFormatMPEG4AAC,
            AVSampleRateKey: 16_000,
            AVNumberOfChannelsKey: 1,
            AVEncoderAudioQualityKey: AVAudioQuality.medium.rawValue,
        ]) else {
            failure = L("voice.micUnavailable")
            return
        }
        recorder.isMeteringEnabled = true
        guard recorder.record() else {
            failure = L("voice.micUnavailable")
            return
        }
        self.recorder = recorder
        isRecording = true
        meter = Task { [weak self] in
            while let self, self.isRecording, !Task.isCancelled {
                recorder.updateMeters()
                self.level = max(0, (recorder.averagePower(forChannel: 0) + 50) / 50)
                try? await Task.sleep(for: .milliseconds(60))
            }
        }
    }

    /// Stop and transcribe. Returns nil when nothing was understood.
    func finish(backend: ChatBackend?) async -> String? {
        guard isRecording, let recorder else { return nil }
        recorder.stop()
        meter?.cancel()
        isRecording = false
        level = 0
        self.recorder = nil
        Task.detached { try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation) }
        guard let audio = try? Data(contentsOf: file), audio.count > 2_000 else { return nil }
        if let backend, let text = try? await backend.transcribe(audio), !text.isEmpty { return text }
        return await Self.onDevice(file)
    }

    func cancel() {
        recorder?.stop()
        meter?.cancel()
        recorder = nil
        isRecording = false
        level = 0
    }

    private static func onDevice(_ url: URL) async -> String? {
        let status = await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { continuation.resume(returning: $0) }
        }
        guard status == .authorized, let recognizer = SFSpeechRecognizer(locale: Preferences.shared.language.locale) ?? SFSpeechRecognizer(),
              recognizer.isAvailable else { return nil }
        let request = SFSpeechURLRecognitionRequest(url: url)
        request.shouldReportPartialResults = false
        return await withCheckedContinuation { continuation in
            var resumed = false
            recognizer.recognitionTask(with: request) { result, error in
                guard !resumed else { return }
                if let result, result.isFinal {
                    resumed = true
                    continuation.resume(returning: result.bestTranscription.formattedString)
                } else if error != nil {
                    resumed = true
                    continuation.resume(returning: nil)
                }
            }
        }
    }
}

/// Reads replies aloud: the backend's voice when it has one, the system voice otherwise.
@Observable
final class Speaker {
    static let shared = Speaker()
    private(set) var isSpeaking = false
    private var player: AVAudioPlayer?
    private let synthesizer = AVSpeechSynthesizer()
    private var job: Task<Void, Never>?

    func speak(_ markdown: String, backend: ChatBackend?) {
        stop()
        let text = Self.plain(markdown)
        guard !text.isEmpty else { return }
        isSpeaking = true
        job = Task {
            try? AVAudioSession.sharedInstance().setCategory(.playback, mode: .spokenAudio)
            try? AVAudioSession.sharedInstance().setActive(true)
            for chunk in Self.chunks(text) {
                if Task.isCancelled { return }
                if let backend, let audio = try? await backend.speech(for: chunk), let player = try? AVAudioPlayer(data: audio) {
                    self.player = player
                    player.play()
                    while player.isPlaying, !Task.isCancelled { try? await Task.sleep(for: .milliseconds(120)) }
                } else {
                    let utterance = AVSpeechUtterance(string: chunk)
                    utterance.voice = AVSpeechSynthesisVoice(language: Self.voiceLanguage(for: chunk))
                    synthesizer.speak(utterance)
                    while synthesizer.isSpeaking, !Task.isCancelled { try? await Task.sleep(for: .milliseconds(120)) }
                }
            }
            isSpeaking = false
        }
    }

    func stop() {
        job?.cancel()
        player?.stop()
        synthesizer.stopSpeaking(at: .immediate)
        isSpeaking = false
    }

    /// Read Chinese text with a Chinese voice whatever the UI language, and vice versa.
    static func voiceLanguage(for text: String) -> String {
        let han = text.unicodeScalars.filter { (0x4E00...0x9FFF).contains($0.value) }.count
        return han * 4 > text.count ? "zh-CN" : "en-US"
    }

    /// Markdown → speakable text.
    static func plain(_ markdown: String) -> String {
        var text = markdown
        text = text.replacingOccurrences(of: "```[\\s\\S]*?```", with: " ", options: .regularExpression)
        text = text.replacingOccurrences(of: "!?\\[([^\\]]*)\\]\\([^)]*\\)", with: "$1", options: .regularExpression)
        text = text.replacingOccurrences(of: "[*_`#>|]", with: "", options: .regularExpression)
        return text.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// Short first chunk so speech starts quickly; later chunks up to 300 characters.
    static func chunks(_ text: String) -> [String] {
        var out: [String] = []
        var current = ""
        for char in text {
            current.append(char)
            let limit = out.isEmpty ? 80 : 300
            if "。！？!?.\n".contains(char) && current.count >= limit / 3 || current.count >= limit {
                out.append(current.trimmingCharacters(in: .whitespacesAndNewlines))
                current = ""
            }
        }
        if !current.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            out.append(current.trimmingCharacters(in: .whitespacesAndNewlines))
        }
        return out.filter { !$0.isEmpty }
    }
}
