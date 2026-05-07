import React, { useState, useEffect, memo, lazy } from "react";
import {
  Loader2,
  BarChart3 as BarChartIcon,
  LineChart as LineChartIcon,
  PieChart as PieChartIcon,
  AreaChart as AreaChartIcon,
  Radar as RadarIcon,
  Layers as StackedIcon,
  Combine as ComposedIcon,
  Target as RadialIcon,
  Activity as ScatterIcon,
  Clock,
  Download,
  Upload,
  Maximize2,
  Minimize2,
  Save,
  Command,
  Code,
} from "lucide-react";
import type { Interaction, SavedPrompt } from "../types";
import { ReportDisplay } from "./ReportDisplay";
import { RawDataTable } from "./RawDataTable";
import { ChartDisplay } from "./ChartDisplay";
import { Timer } from "./Timer";
import { formatTime } from "../utils/formatters";
import "../App.css";

const SavePromptModal = lazy(() => import("./SavePromptModal").then(m => ({ default: m.SavePromptModal })));

const CHART_TYPES = [
  { type: "bar", icon: BarChartIcon, title: "Bar Chart" },
  { type: "stacked-bar", icon: StackedIcon, title: "Stacked Bar" },
  { type: "line", icon: LineChartIcon, title: "Line Chart" },
  { type: "area", icon: AreaChartIcon, title: "Area Chart" },
  { type: "stacked-area", icon: StackedIcon, title: "Stacked Area" },
  { type: "pie", icon: PieChartIcon, title: "Pie Chart" },
  { type: "radar", icon: RadarIcon, title: "Radar Chart" },
  { type: "composed", icon: ComposedIcon, title: "Composed (Line+Bar)" },
  { type: "radial", icon: RadialIcon, title: "Radial Chart" },
  { type: "scatter", icon: ScatterIcon, title: "Scatter Chart" },
];

interface InteractionItemProps {
  interaction: Interaction;
  idx: number;
  chartOverrides: Record<number, string>;
  setChartOverrides: React.Dispatch<
    React.SetStateAction<Record<number, string>>
  >;
  theme: "light" | "dark";
  savedPrompts?: SavedPrompt[];
  setSavedPrompts?: React.Dispatch<React.SetStateAction<SavedPrompt[]>>;
}

export const InteractionItem = memo(
  ({
    interaction,
    idx,
    chartOverrides,
    setChartOverrides,
    setSavedPrompts,
  }: InteractionItemProps) => {
    const result = interaction.result;
    const currentChartType = chartOverrides[idx] || result?.chart_config?.type;
    const [isChartFullscreen, setIsChartFullscreen] = useState(false);
    const [isSaveModalOpen, setIsSaveModalOpen] = useState(false);

    // Handle Escape key to close fullscreen chart
    useEffect(() => {
      const handleKeyDown = (e: KeyboardEvent) => {
        if (e.key === "Escape" && isChartFullscreen) {
          setIsChartFullscreen(false);
        }
      };

      if (isChartFullscreen) {
        window.addEventListener("keydown", handleKeyDown);
      }
      return () => window.removeEventListener("keydown", handleKeyDown);
    }, [isChartFullscreen]);

    const handleSavePrompt = () => {
      if (!result?.sql_query) return;
      setIsSaveModalOpen(true);
    };

    return (
      <div
        id={`interaction-${interaction.id || idx}`}
        className="interaction-wrapper"
      >
        <div className="chat-message user-message">
          <div className="message-content user-message-content">
            {interaction.saved_prompt_name ? (
              <>
                <div className="saved-prompt-label">
                  <Command size={12} /> Saved Prompt
                </div>
                <div>{interaction.saved_prompt_name}</div>
              </>
            ) : (
              interaction.query
            )}
          </div>
        </div>

        {result && result.report && result.report !== "Analyzing..." ? (
          <div className="chat-message ai-message">
            <div className="message-content">


              <div className="report-text markdown-content">
                <ReportDisplay text={result.report} />
                <div className="report-meta">
                  {result.execution_time && result.execution_time > 0 && (
                    <span className="report-meta-item">
                      <Clock size={14} /> {formatTime(result.execution_time)}
                    </span>
                  )}
                  {result.execution_time && result.execution_time < 0 && (
                    <span className="report-meta-item interrupted">
                      <Clock size={14} /> Interrupted
                    </span>
                  )}
                  {interaction.usage && (
                    <>
                      <span className="report-meta-item">
                        <Download size={14} /> In:{" "}
                        {interaction.usage.input_tokens.toLocaleString()}
                      </span>
                      <span className="report-meta-item">
                        <Upload size={14} /> Out:{" "}
                        {interaction.usage.output_tokens.toLocaleString()}
                      </span>
                    </>
                  )}
                  {result.sql_query && (
                    <button
                      onClick={handleSavePrompt}
                      title="Save as Prompt"
                      className="save-prompt-btn"
                    >
                      <Save size={14} /> Save Prompt
                    </button>
                  )}
                </div>
              </div>

              {result.sql_query && result.sql_query !== "No SQL queries were executed." && (
                <details className="sql-accordion">
                  <summary>
                    <Code size={12} className="sql-icon" />
                    View SQL
                  </summary>
                  <div className="sql-content-wrapper">
                    <pre className="sql-code-block">{result.sql_query}</pre>
                  </div>
                </details>
              )}

              {(result.raw_data?.length || 0) > 0 || result.has_data ? (
                <RawDataTable
                  data={result.raw_data || []}
                  hasData={result.has_data}
                  queryId={interaction.id}
                />
              ) : null}

              {result.chart_config && (
                <div className={`chart-wrapper-premium ${isChartFullscreen ? 'fullscreen' : ''}`}>
                  <div className="chart-body">
                    <ChartDisplay
                      type={currentChartType || "bar"}
                      config={result.chart_config}
                    />
                  </div>
                  <div className="chart-toolbar">
                    {CHART_TYPES.map((btn) => (
                      <button
                        key={btn.type}
                        className={`chart-tool-btn ${currentChartType === btn.type ? "active" : ""}`}
                        onClick={() =>
                          setChartOverrides((prev) => ({
                            ...prev,
                            [idx]: btn.type,
                          }))
                        }
                        title={btn.title}
                      >
                        {React.createElement(btn.icon, { size: 12 })}
                      </button>
                    ))}
                    <div className="chart-divider" />
                    <button
                      className="chart-tool-btn"
                      onClick={() => setIsChartFullscreen(!isChartFullscreen)}
                      title={isChartFullscreen ? "Exit Fullscreen" : "Enter Fullscreen"}
                    >
                      {isChartFullscreen ? <Minimize2 size={12} /> : <Maximize2 size={12} />}
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="chat-message ai-message">
            <div className="message-content">
              <div className="loading-indicator-inline">
                <details open className="thinking-accordion">
                  <summary className="thinking-header">
                    <Loader2
                      className="spinner spinner-sm"
                      size={18}
                    />
                    <span className="status-label">
                      {interaction.status &&
                        interaction.status.startsWith("SQL:")
                        ? "Generating insights from database..."
                        : interaction.status || "Analyzing..."}
                    </span>
                    <Timer className="execution-timer" />
                  </summary>
                  {interaction.status &&
                    interaction.status.startsWith("SQL:") && (
                      <div className="status-text-bubble">
                        {interaction.status.replace(/^SQL:\s*/i, "")}
                      </div>
                    )}
                </details>
              </div>
            </div>
          </div>
        )}

        {isSaveModalOpen && result?.sql_query && (
          <React.Suspense fallback={null}>
            <SavePromptModal
              isOpen={isSaveModalOpen}
              onClose={() => setIsSaveModalOpen(false)}
              defaultName={interaction.query.slice(0, 50)}
              query={interaction.query}
              sqlCommand={result.sql_query}
              setSavedPrompts={setSavedPrompts}
            />
          </React.Suspense>
        )}
      </div>
    );
  },
);
