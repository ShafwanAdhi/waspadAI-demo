import type { Metadata } from "next";
import { ChatWorkspace } from "@/components/chat-workspace";
import { SiteHeader } from "@/components/site-header";

export const metadata: Metadata = {
  title: "Periksa Informasi",
};

export default function ChatPage() {
  return (
    <main className="inner-page chat-page overflow-guard">
      <SiteHeader />
      <ChatWorkspace />
    </main>
  );
}
