import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SelectionProvider } from "./state/SelectionContext";
import { WatchlistProvider } from "./state/WatchlistContext";
import { ThemeProvider } from "./state/ThemeContext";
import { ToastProvider } from "./components/Toast";
import App from "./App";
import "./styles/base.css";

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, retry: 1 } },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <ToastProvider>
          <BrowserRouter>
            <SelectionProvider>
              <WatchlistProvider>
                <App />
              </WatchlistProvider>
            </SelectionProvider>
          </BrowserRouter>
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
