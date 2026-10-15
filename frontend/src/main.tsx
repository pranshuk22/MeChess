import { createRoot } from "react-dom/client";
import { App } from "./App";
import { bootstrapSession } from "./api/session";
import "./styles.css";

bootstrapSession().finally(() => createRoot(document.getElementById("root")!).render(<App />));
