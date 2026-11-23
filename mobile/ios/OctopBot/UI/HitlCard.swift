import SwiftUI

/// Docked above the composer while the Bot waits on the user: a question, or a tool approval.
struct HitlCard: View {
    let chat: ChatSession
    let pause: HitlPause

    var body: some View {
        Group {
            if pause.isQuestion && !pause.questions.isEmpty {
                QuestionCard(chat: chat, pause: pause)
            } else {
                ApprovalCard(chat: chat, pause: pause)
            }
        }
        .padding(14)
        .background(Palette.surface, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 22, style: .continuous).stroke(chat.bot.accent.opacity(0.45), lineWidth: 1))
        .padding(.horizontal, 12)
        .padding(.bottom, 6)
        .transition(.move(edge: .bottom).combined(with: .opacity))
    }
}

private struct QuestionCard: View {
    let chat: ChatSession
    let pause: HitlPause
    @State private var answers: [HitlPause.Answer] = []
    @State private var current = 0
    @State private var collapsed = false
    @FocusState private var focused: Int?

    private var message: String? { HitlPause.answerMessage(pause.questions, answers) }
    private var count: Int { pause.questions.count }
    private var currentAnswered: Bool {
        answers.indices.contains(current) && HitlPause.answerText(pause.questions[current], answers[current]) != nil
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                Button { withAnimation(.snappy) { collapsed.toggle() } } label: {
                    HStack(spacing: 8) {
                        CharacterView(look: chat.bot.look, size: 22, motion: .waiting, seed: chat.bot.id)
                        Text("hitl.ask.title").font(.subheadline.weight(.semibold))
                        if count > 1 {
                            Text(verbatim: "\(current + 1)/\(count)").font(.caption.monospacedDigit()).foregroundStyle(Palette.secondary)
                        }
                        Image(systemName: collapsed ? "chevron.up" : "chevron.down")
                            .font(.caption2.weight(.bold)).foregroundStyle(Palette.secondary)
                    }
                }
                .buttonStyle(.plain)
                Spacer()
                Button { chat.dismissQuestion(pause) } label: {
                    Image(systemName: "xmark").font(.footnote.weight(.semibold)).frame(width: 28, height: 28)
                        .background(Palette.raised, in: Circle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(Text("common.close"))
            }
            if collapsed {
                Text(pause.questions[current].question).font(.footnote).foregroundStyle(Palette.secondary).lineLimit(1)
            } else {
                ScrollView {
                    questionView(pause.questions[current], index: current)
                        .id(current)
                        .transition(.asymmetric(insertion: .move(edge: .trailing), removal: .move(edge: .leading)).combined(with: .opacity))
                }
                .frame(maxHeight: 260)
                .fixedSize(horizontal: false, vertical: true)
                HStack(spacing: 10) {
                    if current > 0 {
                        Button { withAnimation(.snappy) { current -= 1 } } label: { Image(systemName: "chevron.left") }
                            .buttonStyle(PillButtonStyle())
                            .accessibilityLabel(Text("common.back"))
                    }
                    Button("hitl.ask.skip") { chat.answer(pause, text: L("hitl.ask.skipMessage")) }
                        .buttonStyle(PillButtonStyle())
                    Spacer()
                    if current < count - 1 {
                        Button("hitl.ask.next") {
                            Haptics.tap()
                            withAnimation(.snappy) { current += 1 }
                        }
                        .buttonStyle(PillButtonStyle(filled: true))
                        .disabled(!currentAnswered)
                        .opacity(currentAnswered ? 1 : 0.4)
                    } else {
                        Button("hitl.ask.submit") {
                            if let message { Haptics.tap(); chat.answer(pause, text: message) }
                        }
                        .buttonStyle(PillButtonStyle(filled: true))
                        .disabled(message == nil || chat.isStreaming)
                        .opacity(message == nil ? 0.4 : 1)
                    }
                }
            }
        }
        .foregroundStyle(Palette.text)
        .onAppear {
            if answers.count != count { answers = Array(repeating: .init(), count: count) }
        }
    }

    @ViewBuilder
    private func questionView(_ question: HitlPause.Question, index: Int) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            if let header = question.header, !header.isEmpty, header != question.question {
                Text(header).font(.caption.weight(.semibold)).foregroundStyle(chat.bot.accent)
            }
            Text(question.question).font(.callout.weight(.medium))
            ForEach(question.options, id: \.label) { option in
                let picked = answers.indices.contains(index) && answers[index].picked.contains(option.label)
                Button { toggle(option.label, in: index, multi: question.multiSelect) } label: {
                    HStack(alignment: .top, spacing: 10) {
                        Image(systemName: picked ? (question.multiSelect ? "checkmark.square.fill" : "checkmark.circle.fill")
                                                 : (question.multiSelect ? "square" : "circle"))
                            .foregroundStyle(picked ? chat.bot.accent : Palette.secondary)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(option.label).foregroundStyle(Palette.text)
                            if let detail = option.description, !detail.isEmpty {
                                Text(detail).font(.caption).foregroundStyle(Palette.secondary)
                            }
                        }
                        Spacer(minLength: 0)
                    }
                    .padding(.vertical, 8)
                    .padding(.horizontal, 10)
                    .background(picked ? chat.bot.accent.opacity(0.12) : Palette.raised, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                }
                .buttonStyle(.plain)
            }
            TextField(question.options.isEmpty ? "hitl.ask.placeholder" : "hitl.ask.other", text: otherBinding(index), axis: .vertical)
                .lineLimit(1...4)
                .focused($focused, equals: index)
                .padding(.vertical, 8)
                .padding(.horizontal, 10)
                .background(Palette.raised, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        }
        .font(.subheadline)
    }

    private func toggle(_ label: String, in index: Int, multi: Bool) {
        guard answers.indices.contains(index) else { return }
        Haptics.tap()
        if multi {
            if let at = answers[index].picked.firstIndex(of: label) {
                answers[index].picked.remove(at: at)
            } else {
                answers[index].picked.append(label)
            }
        } else {
            let picking = answers[index].picked != [label]
            answers[index].picked = picking ? [label] : []
            answers[index].other = ""
            // One choice is the whole answer: move on by itself.
            if picking, index == current, current < count - 1 {
                Task {
                    try? await Task.sleep(for: .milliseconds(280))
                    if current == index { withAnimation(.snappy) { current += 1 } }
                }
            }
        }
    }

    private func otherBinding(_ index: Int) -> Binding<String> {
        Binding {
            answers.indices.contains(index) ? answers[index].other : ""
        } set: { value in
            guard answers.indices.contains(index) else { return }
            answers[index].other = value
            // A typed answer replaces a single choice.
            if !value.isEmpty, !(pause.questions[index].multiSelect) { answers[index].picked = [] }
        }
    }
}

private struct ApprovalCard: View {
    let chat: ChatSession
    let pause: HitlPause

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                Image(systemName: "hand.raised.fill").foregroundStyle(.orange)
                Text("hitl.title").font(.subheadline.weight(.semibold))
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 10) {
                    ForEach(Array(pause.actions.enumerated()), id: \.offset) { _, action in
                        VStack(alignment: .leading, spacing: 4) {
                            Text(action.label).font(.callout.weight(.semibold))
                            if let description = action.description {
                                Text(description).font(.footnote).foregroundStyle(Palette.secondary)
                            }
                            ForEach(action.details, id: \.self) { detail in
                                Text(detail.value)
                                    .font(.system(.caption, design: .monospaced))
                                    .lineLimit(4)
                                    .padding(8)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .background(Palette.raised, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                            }
                        }
                    }
                }
            }
            .frame(maxHeight: 220)
            .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 10) {
                Button("hitl.reject", role: .destructive) { chat.decide(pause, approve: false) }
                    .buttonStyle(PillButtonStyle())
                Spacer()
                Button("hitl.approve") {
                    Haptics.tap()
                    chat.decide(pause, approve: true)
                }
                .buttonStyle(PillButtonStyle(filled: true))
            }
            .disabled(chat.isStreaming)
        }
        .foregroundStyle(Palette.text)
    }
}
