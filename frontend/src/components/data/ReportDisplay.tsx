import { memo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface ReportDisplayProps {
  text: string;
}

export const ReportDisplay = memo(({ text }: ReportDisplayProps) => {
  return <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>;
});
