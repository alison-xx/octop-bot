import SwiftUI

/// DS Bot character geometry and inks (Apache-2.0, see dashboard/public/licenses/ds-bot.txt).
struct CharacterShape {
    var label: String
    var body: Path
    var shade: Path?
    var light: Path?
    /// Soft characters: one flat body and plain white capsule eyes (no shade, light or pupils).
    var flat = false
    var eyes: [Eye]
    var paints: [(path: Path, color: Color, opacity: Double)]

    struct Eye { var x, y, w, h, angle: CGFloat }
}

enum Characters {
    static let library = load()

    struct Library {
        var shapes: [String: CharacterShape]
        var order: [String]
        var inks: [String: (light: Color, dark: Color)]
        var inkOrder: [String]
        var aurora: [Gradient.Stop]
    }

    static var shapeIds: [String] { ["octop"] + library.order }
    static var inkIds: [String] { library.inkOrder }

    /// The ink for the current light / dark appearance.
    static func ink(_ color: String) -> Color {
        let pair = inkPair(color)
        return Color(UIColor { traits in
            UIColor(traits.userInterfaceStyle == .dark ? pair.dark : pair.light)
        })
    }

    static func ink(_ color: String, dark: Bool) -> Color {
        let pair = inkPair(color)
        return dark ? pair.dark : pair.light
    }

    private static func inkPair(_ color: String) -> (light: Color, dark: Color) {
        if let ink = library.inks[color] { return ink }
        if let hex = Color(hex: color) { return (hex, hex) }
        return library.inks["blue"] ?? (.blue, .blue)
    }

    static func shape(_ id: String) -> CharacterShape? {
        library.shapes[id] ?? library.shapes["gumdrop"]
    }

    /// DS Bot characters plus the dashboard's soft characters, merged like the dashboard does:
    /// soft shapes first, soft inks override DS inks of the same name.
    private static func load() -> Library {
        func read(_ name: String) -> Data? {
            Bundle.main.url(forResource: name, withExtension: "json").flatMap { try? Data(contentsOf: $0) }
        }
        let ds = read("characters").map(parse) ?? Library(shapes: [:], order: [], inks: [:], inkOrder: [], aurora: [])
        guard let soft = read("soft-characters").map(parse) else { return ds }
        return merge(ds: ds, soft: soft)
    }

    static func merge(ds: Library, soft: Library) -> Library {
        Library(
            shapes: soft.shapes.merging(ds.shapes) { _, dsShape in dsShape },
            order: soft.order + ds.order.filter { !soft.order.contains($0) },
            inks: ds.inks.merging(soft.inks) { _, softInk in softInk },
            inkOrder: soft.inkOrder + ds.inkOrder.filter { !soft.inkOrder.contains($0) },
            aurora: ds.aurora
        )
    }

    static func parse(_ data: Data) -> Library {
        guard let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return Library(shapes: [:], order: [], inks: [:], inkOrder: [], aurora: [])
        }
        let shapeOrder = orderedKeys(of: "shapes", in: data)
        let inkOrder = orderedKeys(of: "inks", in: data)
        var shapes: [String: CharacterShape] = [:]
        for (id, value) in root["shapes"] as? [String: [String: Any]] ?? [:] {
            guard let body = value["body"] as? String else { continue }
            let eyes = (value["eyes"] as? [[Double]] ?? []).compactMap { e -> CharacterShape.Eye? in
                e.count >= 5 ? .init(x: e[0], y: e[1], w: e[2], h: e[3], angle: e[4]) : nil
            }
            let paints = (value["paints"] as? [[Any]] ?? []).compactMap { p -> (Path, Color, Double)? in
                guard p.count >= 3, let d = p[0] as? String, let color = (p[1] as? String).flatMap(Color.init(hex:)) else { return nil }
                return (SVGPath.parse(d), color, (p[2] as? Double) ?? 1)
            }
            shapes[id] = CharacterShape(
                label: value["label"] as? String ?? id,
                body: SVGPath.parse(body),
                shade: (value["shade"] as? String).map(SVGPath.parse),
                light: (value["light"] as? String).map(SVGPath.parse),
                flat: value["flat"] as? Bool ?? false,
                eyes: eyes,
                paints: paints
            )
        }
        var inks: [String: (Color, Color)] = [:]
        for (id, pair) in root["inks"] as? [String: [String]] ?? [:] where pair.count == 2 {
            if let light = Color(hex: pair[0]), let dark = Color(hex: pair[1]) { inks[id] = (light, dark) }
        }
        let aurora = ((root["gradients"] as? [String: [[Any]]])?["aurora"] ?? []).compactMap { stop -> Gradient.Stop? in
            guard stop.count == 2, let offset = (stop[0] as? NSNumber)?.doubleValue,
                  let color = (stop[1] as? String).flatMap(Color.init(hex:)) else { return nil }
            return Gradient.Stop(color: color, location: offset)
        }
        return Library(shapes: shapes, order: shapeOrder.filter { shapes[$0] != nil }, inks: inks, inkOrder: inkOrder.filter { inks[$0] != nil }, aurora: aurora)
    }

    /// JSONSerialization loses key order; keep the file's order for pickers.
    private static func orderedKeys(of section: String, in data: Data) -> [String] {
        let text = String(decoding: data, as: UTF8.self)
        guard let start = text.range(of: "\"\(section)\"") else { return [] }
        var depth = 0
        var keys: [String] = []
        var index = text[start.upperBound...].firstIndex(of: "{")!
        var inString = false
        var current = ""
        var escaped = false
        while index < text.endIndex {
            let char = text[index]
            if inString {
                if escaped { escaped = false; current.append(char) }
                else if char == "\\" { escaped = true }
                else if char == "\"" {
                    inString = false
                    if depth == 1 {
                        var look = text.index(after: index)
                        while look < text.endIndex, text[look] == " " { look = text.index(after: look) }
                        if look < text.endIndex, text[look] == ":" { keys.append(current) }
                    }
                } else { current.append(char) }
            } else if char == "\"" {
                inString = true
                current = ""
            } else if char == "{" || char == "[" {
                depth += 1
            } else if char == "}" || char == "]" {
                depth -= 1
                if depth == 0 { break }
            }
            index = text.index(after: index)
        }
        return keys
    }
}

/// SVG path data → `Path`: every command (M L H V C S Q T A Z, absolute and relative) and compact numbers.
enum SVGPath {
    static func parse(_ d: String) -> Path {
        var path = Path()
        var scanner = NumberScanner(d)
        var command: Character = "M"
        var point = CGPoint.zero
        var start = CGPoint.zero
        var lastControl: CGPoint?
        var lastCommand: Character = "M"

        while let next = scanner.peekCommand() {
            if let next { command = next; scanner.skip() }
            let relative = command.isLowercase
            func p(_ x: CGFloat, _ y: CGFloat) -> CGPoint { relative ? CGPoint(x: point.x + x, y: point.y + y) : CGPoint(x: x, y: y) }
            func reflected() -> CGPoint {
                guard let lastControl else { return point }
                return CGPoint(x: 2 * point.x - lastControl.x, y: 2 * point.y - lastControl.y)
            }
            var control: CGPoint?
            switch command.uppercased().first! {
            case "M":
                guard let x = scanner.number(), let y = scanner.number() else { return path }
                point = p(x, y)
                start = point
                path.move(to: point)
                // Extra pairs after a moveto are implicit linetos.
                command = relative ? "l" : "L"
            case "L":
                guard let x = scanner.number(), let y = scanner.number() else { return path }
                point = p(x, y)
                path.addLine(to: point)
            case "H":
                guard let x = scanner.number() else { return path }
                point = CGPoint(x: relative ? point.x + x : x, y: point.y)
                path.addLine(to: point)
            case "V":
                guard let y = scanner.number() else { return path }
                point = CGPoint(x: point.x, y: relative ? point.y + y : y)
                path.addLine(to: point)
            case "C":
                guard let x1 = scanner.number(), let y1 = scanner.number(), let x2 = scanner.number(),
                      let y2 = scanner.number(), let x = scanner.number(), let y = scanner.number() else { return path }
                let c1 = p(x1, y1), c2 = p(x2, y2), end = p(x, y)
                path.addCurve(to: end, control1: c1, control2: c2)
                control = c2
                point = end
            case "S":
                guard let x2 = scanner.number(), let y2 = scanner.number(), let x = scanner.number(), let y = scanner.number() else { return path }
                let c1 = "CScs".contains(lastCommand) ? reflected() : point
                let c2 = p(x2, y2), end = p(x, y)
                path.addCurve(to: end, control1: c1, control2: c2)
                control = c2
                point = end
            case "Q":
                guard let x1 = scanner.number(), let y1 = scanner.number(), let x = scanner.number(), let y = scanner.number() else { return path }
                let c = p(x1, y1), end = p(x, y)
                path.addQuadCurve(to: end, control: c)
                control = c
                point = end
            case "T":
                guard let x = scanner.number(), let y = scanner.number() else { return path }
                let c = "QTqt".contains(lastCommand) ? reflected() : point
                let end = p(x, y)
                path.addQuadCurve(to: end, control: c)
                control = c
                point = end
            case "A":
                guard let rx = scanner.number(), let ry = scanner.number(), let angle = scanner.number(),
                      let large = scanner.flag(), let sweep = scanner.flag(),
                      let x = scanner.number(), let y = scanner.number() else { return path }
                let end = p(x, y)
                addArc(to: &path, from: point, to: end, rx: rx, ry: ry, angle: angle, large: large, sweep: sweep)
                point = end
            case "Z":
                path.closeSubpath()
                point = start
            default:
                return path
            }
            lastControl = control
            lastCommand = command
        }
        return path
    }

    /// SVG elliptical arc (endpoint form) as cubic Béziers.
    static func addArc(
        to path: inout Path, from p0: CGPoint, to p1: CGPoint, rx: CGFloat, ry: CGFloat,
        angle: CGFloat, large: Bool, sweep: Bool
    ) {
        var rx = abs(rx), ry = abs(ry)
        guard rx > 0, ry > 0, p0 != p1 else { path.addLine(to: p1); return }
        let phi = angle * .pi / 180
        let cosPhi = cos(phi), sinPhi = sin(phi)
        let dx = (p0.x - p1.x) / 2, dy = (p0.y - p1.y) / 2
        let x1 = cosPhi * dx + sinPhi * dy
        let y1 = -sinPhi * dx + cosPhi * dy
        let lambda = (x1 * x1) / (rx * rx) + (y1 * y1) / (ry * ry)
        if lambda > 1 { rx *= sqrt(lambda); ry *= sqrt(lambda) }
        let num = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1
        let den = rx * rx * y1 * y1 + ry * ry * x1 * x1
        var coef = sqrt(max(0, num / den))
        if large == sweep { coef = -coef }
        let cx1 = coef * rx * y1 / ry
        let cy1 = -coef * ry * x1 / rx
        let cx = cosPhi * cx1 - sinPhi * cy1 + (p0.x + p1.x) / 2
        let cy = sinPhi * cx1 + cosPhi * cy1 + (p0.y + p1.y) / 2
        func angleOf(_ ux: CGFloat, _ uy: CGFloat) -> CGFloat { atan2(uy, ux) }
        let theta1 = angleOf((x1 - cx1) / rx, (y1 - cy1) / ry)
        var delta = angleOf((-x1 - cx1) / rx, (-y1 - cy1) / ry) - theta1
        if !sweep && delta > 0 { delta -= 2 * .pi }
        if sweep && delta < 0 { delta += 2 * .pi }
        let segments = max(1, Int(ceil(abs(delta) / (.pi / 2))))
        let step = delta / CGFloat(segments)
        let k = 4 / 3 * tan(step / 4)
        func onEllipse(_ t: CGFloat) -> CGPoint {
            CGPoint(x: cx + rx * cos(t) * cosPhi - ry * sin(t) * sinPhi, y: cy + rx * cos(t) * sinPhi + ry * sin(t) * cosPhi)
        }
        func derivative(_ t: CGFloat) -> CGPoint {
            CGPoint(x: -rx * sin(t) * cosPhi - ry * cos(t) * sinPhi, y: -rx * sin(t) * sinPhi + ry * cos(t) * cosPhi)
        }
        var t = theta1
        for index in 0..<segments {
            let t2 = t + step
            let a = onEllipse(t), b = index == segments - 1 ? p1 : onEllipse(t2)
            let da = derivative(t), db = derivative(t2)
            path.addCurve(
                to: b,
                control1: CGPoint(x: a.x + k * da.x, y: a.y + k * da.y),
                control2: CGPoint(x: b.x - k * db.x, y: b.y - k * db.y)
            )
            t = t2
        }
    }

    struct NumberScanner {
        let chars: [Character]
        var index = 0
        init(_ text: String) { chars = Array(text) }

        mutating func skipSeparators() {
            while index < chars.count, chars[index].isWhitespace || chars[index] == "," { index += 1 }
        }

        /// `.some(letter)` when a command letter is next, `.some(nil)` when a number follows, `nil` at the end.
        mutating func peekCommand() -> Character?? {
            skipSeparators()
            guard index < chars.count else { return nil }
            let c = chars[index]
            return c.isLetter && c != "e" && c != "E" ? .some(c) : .some(nil)
        }

        mutating func skip() { index += 1 }

        /// Arc flags may be written without separators ("a5 5 0 105 5").
        mutating func flag() -> Bool? {
            skipSeparators()
            guard index < chars.count, chars[index] == "0" || chars[index] == "1" else { return nil }
            defer { index += 1 }
            return chars[index] == "1"
        }

        mutating func number() -> CGFloat? {
            skipSeparators()
            let begin = index
            if index < chars.count, chars[index] == "-" || chars[index] == "+" { index += 1 }
            var dot = false
            while index < chars.count {
                let c = chars[index]
                if c.isNumber { index += 1 }
                else if c == ".", !dot { dot = true; index += 1 }
                else if c == "e" || c == "E" {
                    index += 1
                    if index < chars.count, chars[index] == "-" || chars[index] == "+" { index += 1 }
                } else { break }
            }
            guard index > begin, let value = Double(String(chars[begin..<index])) else { return nil }
            return CGFloat(value)
        }
    }
}

extension Color {
    init?(hex: String) {
        var text = hex.trimmingCharacters(in: .whitespaces)
        guard text.hasPrefix("#") else { return nil }
        text.removeFirst()
        guard text.count == 6, let value = UInt32(text, radix: 16) else { return nil }
        self.init(
            red: Double((value >> 16) & 0xFF) / 255,
            green: Double((value >> 8) & 0xFF) / 255,
            blue: Double(value & 0xFF) / 255
        )
    }
}
