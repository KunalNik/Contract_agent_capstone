import React, { KeyboardEvent, useEffect, useRef } from "react";
import { Textarea } from "../../shared/ui/textarea";
import {
    Select,
    SelectContent,
    SelectGroup,
    SelectItem,
    SelectTrigger,
    SelectValue
} from "../../shared/ui/select";
import { Button } from "../../shared/ui/button";
import { fetchEventSource } from '@microsoft/fetch-event-source';
import { MouseEvent } from 'react';
import { SendHorizontal } from "lucide-react";
import { Message, MessagePart, useChat } from "./provider";

export function ChatInput() {
    const history = useRef<string[]>([])
    const [submiting, setSubmiting] = React.useState(false);
    const { addMessage, addMessagePart, updateMessageGenerating, clearAiParts, reset } = useChat();
    // Only offer models the backend actually initialised (depends on configured API keys)
    const [models, setModels] = React.useState<string[]>(["gemini-2.5-flash"]);

    useEffect(() => {
        fetch("/api/documents/status")
            .then((r) => (r.ok ? r.json() : null))
            .then((data) => {
                if (data?.available_models?.length) setModels(data.available_models);
            })
            .catch(() => { /* keep the default */ });
    }, []);
    const textareaRef = useRef<HTMLTextAreaElement>(null);

    const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        const form = event.currentTarget;
        const formData = new FormData(form);
        const model = formData.get("model") as string;
        const prompt = formData.get("prompt") as string;

        if (!prompt.trim()) {
            return;
        }

        const userMessage: Message = {
            id: Date.now().toString(),
            type: "user",
            parts: [{ content: prompt, type: "user_message" }],
            generating: false
        };

        const aiMessage: Message = {
            id: Date.now().toString() + "ai",
            type: "ai",
            parts: [],
            generating: true
        };

        addMessage(userMessage);
        addMessage(aiMessage);
        // removed console log

        // Clear the form after submission
        form.reset();

        await fetchEventSource('/api/run/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ model, prompt, history: JSON.stringify(history.current) }),
            onmessage(event) {
                const data: MessagePart = JSON.parse(event.data);

                if (data.type === "end") {
                    updateMessageGenerating(aiMessage.id, false);
                } else if (data.type === "history") {
                    // The server sends the full conversation; replace, never append,
                    // otherwise the history doubles on every turn.
                    history.current = data.content as unknown as string[];
                } else if (data.type === "retract") {
                    clearAiParts(aiMessage.id);
                } else {
                    addMessagePart(aiMessage.id, data);
                }
            },
            async onopen() {
                setSubmiting(true);
            },
            onclose() {
                setSubmiting(false);
                // Stop the spinner even if the stream ended without an 'end' event
                updateMessageGenerating(aiMessage.id, false);
            },
            onerror() {
                setSubmiting(false);
                // removed console error
                addMessagePart(aiMessage.id, { type: "ai_message", content: "Error: Failed to generate the response." });
                updateMessageGenerating(aiMessage.id, false);
                throw new Error('Connection closed due to error');
            }
        });
    };

    const handleClear = (event: MouseEvent<HTMLButtonElement>) => {
        event.preventDefault();
        reset();
        history.current = [];
        if (textareaRef.current) {
            textareaRef.current.value = "";
        }
    };

    const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            const form = event.currentTarget.form;
            if (form) {
                form.requestSubmit();
            }
        }
    };

    return (
        <div className="flex-0">
            <form className="flex flex-col gap-2 relative" onSubmit={handleSubmit}>
                <Textarea
                    name="prompt"
                    className="m-0 max-h-[400px]"
                    placeholder="Type your prompt here!"
                    onKeyDown={handleKeyDown}
                    ref={textareaRef}
                />
                <div className="flex gap-2">
                    <Select key={models.join(",")} name="model" defaultValue={models[0]}>
                        <SelectTrigger className=" flex-1 text-foreground">
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectGroup>
                                {models.map((m) => (
                                    <SelectItem key={m} value={m}>{m}</SelectItem>
                                ))}
                            </SelectGroup>
                        </SelectContent>
                    </Select>
                    <Button variant="outline" className="flex-0" onClick={handleClear}>
                        Reset
                    </Button>
                    <Button className="flex-0" type="submit" disabled={submiting}>
                        Send your prompt now!
                        <SendHorizontal />
                    </Button>
                </div>
            </form>
        </div>
    );
}