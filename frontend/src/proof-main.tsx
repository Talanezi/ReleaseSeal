import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { JudgeProofApp } from "./JudgeProofApp";
import "./styles.css";

const root = document.getElementById("root");
if (!root) throw new Error("Root element was not found");

createRoot(root).render(<StrictMode><JudgeProofApp /></StrictMode>);
