import type React from "react";
import { memo } from "react";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";
import "highlight.js/styles/github-dark.css";

interface MarkdownProps {
	children: string;
}

/**
 * Renders assistant text as GitHub-flavored Markdown with syntax-highlighted
 * code blocks. Raw HTML is intentionally NOT enabled (no rehype-raw) so model
 * output cannot inject markup.
 */
const Markdown: React.FC<MarkdownProps> = ({ children }) => (
	<div className="md">
		<ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
			{children}
		</ReactMarkdown>
	</div>
);

export default memo(Markdown);
