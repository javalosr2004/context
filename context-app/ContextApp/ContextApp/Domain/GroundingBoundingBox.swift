import Foundation

struct GroundingBoundingBox: Equatable {
    let x: CGFloat
    let y: CGFloat
    let width: CGFloat
    let height: CGFloat

    init?(values: [Double]) {
        guard values.count == 4 else { return nil }
        guard values.allSatisfy(\.isFinite) else { return nil }
        guard values[0] >= 0, values[1] >= 0 else { return nil }
        guard values[2] > 0, values[3] > 0 else { return nil }
        guard values[0] + values[2] <= 1, values[1] + values[3] <= 1 else { return nil }

        x = CGFloat(values[0])
        y = CGFloat(values[1])
        width = CGFloat(values[2])
        height = CGFloat(values[3])
    }

    func screenRect(captureSize: CGSize, screenFrame: CGRect) -> CGRect? {
        guard captureSize.width > 0, captureSize.height > 0 else { return nil }

        let rectWidth = width * screenFrame.width
        let rectHeight = height * screenFrame.height
        let originX = screenFrame.minX + (x * screenFrame.width)
        let originY = screenFrame.maxY - ((y + height) * screenFrame.height)

        return CGRect(x: originX, y: originY, width: rectWidth, height: rectHeight)
    }
}

struct GroundingResponse: Decodable {
    let boundingBox: GroundingBoundingBox

    private enum CodingKeys: String, CodingKey {
        case boundingBox = "bounding_box"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let values = try container.decode([Double].self, forKey: .boundingBox)
        guard let boundingBox = GroundingBoundingBox(values: values) else {
            throw DecodingError.dataCorruptedError(
                forKey: .boundingBox,
                in: container,
                debugDescription: "Expected normalized [x, y, width, height] within [0, 1]."
            )
        }

        self.boundingBox = boundingBox
    }
}
