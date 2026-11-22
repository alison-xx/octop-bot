import SwiftUI

/// Full-screen talk mode: tap to speak, the Bot answers out loud.
struct VoiceModeView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let chat: ChatSession
    @State private var recorder = VoiceRecorder()
    @State private var heard = ""
    @State private var transcribing = false
    /// Only replies from this voice session are shown.
    @State private var firstMessage = 0
    private let speaker = Speaker.shared

    private var motion: BotMotion {
        if recorder.isRecording { return .searching }
        if transcribing { return .thinking }
        if chat.isStreaming { return chat.motion }
        if speaker.isSpeaking { return .working }
        return .idle
    }

    private var status: LocalizedStringKey {
        if recorder.isRecording { return "voice.listening" }
        if transcribing { return "voice.transcribing" }
        if chat.isStreaming { return "voice.thinking" }
        if speaker.isSpeaking { return "voice.speaking" }
        return "voice.tapToTalk"
    }

    var body: some View {
        ZStack {
            Palette.background.ignoresSafeArea()
            RadialGradient(colors: [chat.bot.accent.opacity(0.28), .clear], center: .center, startRadius: 10, endRadius: 320)
                .ignoresSafeArea()
            VStack(spacing: 24) {
                HStack {
                    Button { close() } label: {
                        Image(systemName: "xmark").font(.title3.weight(.semibold)).frame(width: 44, height: 44)
                            .background(Palette.surface, in: Circle())
                    }
                    Spacer()
                }
                .padding(.horizontal, 20)
                Spacer()
                CharacterView(look: chat.bot.look, size: 220, motion: motion, seed: chat.bot.id)
                    .scaleEffect(1 + CGFloat(recorder.level) * 0.08)
                    .animation(.easeOut(duration: 0.12), value: recorder.level)
                Text(chat.bot.name).font(.system(.title, design: .rounded).weight(.semibold))
                Text(status).font(.headline).foregroundStyle(Palette.secondary)
                ScrollView {
                    VStack(spacing: 10) {
                        if let failure = recorder.failure {
                            Text(failure).font(.body).foregroundStyle(.red).multilineTextAlignment(.center)
                        }
                        if !heard.isEmpty {
                            Text(heard).font(.body).foregroundStyle(Palette.secondary).multilineTextAlignment(.center)
                        }
                        if let reply = lastReply, !reply.isEmpty {
                            Text(Speaker.plain(reply)).font(.title3).multilineTextAlignment(.center)
                        }
                    }
                    .padding(.horizontal, 28)
                }
                .frame(maxHeight: 200)
                Spacer()
                Button(action: toggle) {
                    Image(systemName: recorder.isRecording ? "arrow.up" : (speaker.isSpeaking || chat.isStreaming ? "stop.fill" : "mic.fill"))
                        .font(.system(size: 30, weight: .semibold))
                        .frame(width: 84, height: 84)
                        .background(recorder.isRecording ? chat.bot.accent : Palette.text, in: Circle())
                        .foregroundStyle(recorder.isRecording ? .white : Palette.background)
                }
                .disabled(transcribing)
                .accessibilityLabel(Text(status))
                .padding(.bottom, 32)
            }
        }
        .onAppear {
            firstMessage = chat.messages.count
            chat.onReply = { text in speaker.speak(text, backend: model.backend) }
        }
        .onDisappear {
            chat.onReply = nil
            recorder.cancel()
            speaker.stop()
        }
    }

    private var lastReply: String? {
        chat.messages.dropFirst(firstMessage).last { $0.role == .assistant }?.text
    }

    private func toggle() {
        if speaker.isSpeaking || chat.isStreaming {
            speaker.stop()
            chat.stop()
            return
        }
        Task {
            if recorder.isRecording {
                transcribing = true
                let text = await recorder.finish(backend: model.backend)
                transcribing = false
                guard let text, !text.isEmpty else { heard = L("voice.notHeard"); return }
                heard = text
                chat.send(text)
            } else {
                heard = ""
                await recorder.start()
            }
        }
    }

    private func close() {
        recorder.cancel()
        speaker.stop()
        dismiss()
    }
}
