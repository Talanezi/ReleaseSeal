import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { PRODUCT_NAME } from "./brand";
import "./styles.css";

document.title = PRODUCT_NAME;

const root = document.getElementById("root");

if (!root) {
  throw new Error("Root element was not found");
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
