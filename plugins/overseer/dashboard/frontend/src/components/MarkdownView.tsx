import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/** The one place markdown rendering is configured. Raw HTML is inert by
 * default (react-markdown skips it) — do not add rehype-raw. */
function MarkdownView({ text }: { text: string }) {
  return (
    <div className="md-view">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  );
}

export default MarkdownView;
