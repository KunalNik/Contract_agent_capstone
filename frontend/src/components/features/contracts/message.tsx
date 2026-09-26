import { Fragment } from "react";
import { Loader } from "../../shared/ui/loader";
import { Message, MessagePartContent } from "./provider";

function toText(content: MessagePartContent): string {
    if (typeof content === "string") return content;
    if (Array.isArray(content)) {
        return content.map((c) => (typeof c === "string" ? c : c.text ?? JSON.stringify(c))).join("");
    }
    return content.text ?? JSON.stringify(content);
}

interface Props {
    message: Message;
}

export function ChatMessage({ message }: Props) {
    const { type, parts, generating, } = message;
    return (
        <div className={`py-3 gap-0 ${type === "ai" ? "opacity-100" : "opacity-60"}`}>
            <strong className="text-xs">{type === "ai" ? "AI" : "USER"}</strong>
            <div>
                {parts.map(({ content, type }, index) => {
                    switch (type) {
                        case "tool_call":
                            return <details key={index} className="my-3 cursor-pointer">
                                <summary>Tool call</summary>
                                <code className="block p-1 bg-muted rounded-sm overflow-x-auto font-mono text-sm">{toText(content)}</code>
                            </details>
                        case "tool_message":
                            return <details key={index} className="my-3 cursor-pointer">
                                <summary>Tool message</summary>
                                <code className="block p-1 bg-muted rounded-sm overflow-x-auto font-mono text-sm">{toText(content)}</code>
                            </details>
                        case "error":
                            return <div key={index} className="my-2 text-sm text-red-600">{toText(content)}</div>;
                        default:
                            return <Fragment key={index}>{toText(content)}</Fragment>;
                    }
                })}
                {generating && (
                    <Loader className="inline-flex" />
                )}
            </div>
        </div>
    );
}
