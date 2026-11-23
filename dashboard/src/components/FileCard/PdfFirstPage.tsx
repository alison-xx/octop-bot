/** First page of a PDF as a card thumbnail (react-pdf, loaded lazily by FilePreview). */
import { Document, Page, pdfjs } from "react-pdf";
import styles from "./FileCard.module.less";

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

export default function PdfFirstPage({
  blob,
  width,
  onError,
}: {
  blob: Blob;
  width: number;
  onError: () => void;
}) {
  // The blob comes from the shared cache, so its identity is stable across renders.
  return (
    <Document
      file={blob}
      loading={null}
      error={null}
      onLoadError={onError}
      onSourceError={onError}
      className={styles.pdfDocument}
    >
      <Page
        pageNumber={1}
        width={width}
        renderTextLayer={false}
        renderAnnotationLayer={false}
        loading={null}
        onRenderError={onError}
      />
    </Document>
  );
}
