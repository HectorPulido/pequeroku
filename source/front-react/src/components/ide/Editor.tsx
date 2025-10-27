import Editor from "@monaco-editor/react";
import type { editor } from "monaco-editor";
import type React from "react";
import { useEffect, useMemo, useRef } from "react";
import type { Theme } from "@/lib/theme";

interface EditorProps {
	content: string;
	onChange: (content: string) => void;
	theme: Theme;
	language: string;
	isMobile?: boolean;
}

const MonacoEditor: React.FC<EditorProps> = ({
	content,
	onChange,
	theme,
	language,
	isMobile = false,
}) => {
	const editorRef = useRef<editor.IStandaloneCodeEditor | null>(null);

	const computedOptions = useMemo<editor.IStandaloneEditorConstructionOptions>(() => {
		return {
			minimap: { enabled: !isMobile },
			fontSize: isMobile ? 16 : 13,
			wordWrap: isMobile ? "on" : "off",
			lineNumbers: isMobile ? "off" : "on",
			glyphMargin: !isMobile,
			folding: !isMobile,
			lineNumbersMinChars: isMobile ? 0 : 4,
			lineDecorationsWidth: isMobile ? 16 : 20,
			scrollbar: isMobile
				? { vertical: "hidden", horizontal: "hidden" }
				: { vertical: "auto", horizontal: "auto" },
			scrollBeyondLastLine: false,
			automaticLayout: true,
			smoothScrolling: !isMobile,
		};
	}, [isMobile]);

	useEffect(() => {
		if (editorRef.current) {
			editorRef.current.updateOptions(computedOptions);
		}
	}, [computedOptions]);

	const handleMount = (instance: editor.IStandaloneCodeEditor) => {
		editorRef.current = instance;
		instance.updateOptions(computedOptions);
	};

	return (
		<div className="flex-1">
			<Editor
				height="100%"
				defaultLanguage="plaintext"
				language={language || "plaintext"}
				theme={theme === "dark" ? "vs-dark" : "vs-light"}
				value={content}
				onChange={(value) => onChange(value || "")}
				onMount={handleMount}
				options={computedOptions}
			/>
		</div>
	);
};

export default MonacoEditor;
