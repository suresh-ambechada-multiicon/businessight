import React, { useState, useEffect, memo } from "react";
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
import { SavePromptModal } from "./SavePromptModal";
import { formatTime } from "../utils/formatters";

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
          <div className="message-content" style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
            {interaction.saved_prompt_name ? (
              <>
                <div style={{ fontSize: "0.8rem", color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: "0.05em", fontWeight: 700, display: "flex", alignItems: "center", gap: "4px" }}>
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
                <div
                  style={{
                    marginTop: "10px",
                    fontSize: "0.8rem",
                    color: "var(--text-tertiary)",
                    display: "flex",
                    gap: "12px",
                    flexWrap: "wrap",
                  }}
                >
                  {result.execution_time && result.execution_time > 0 && (
                    <span
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "4px",
                      }}
                    >
                      <Clock size={14} /> {formatTime(result.execution_time)}
                    </span>
                  )}
                  {result.execution_time && result.execution_time < 0 && (
                    <span
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "4px",
                        color: "var(--danger-color, #ef4444)",
                      }}
                    >
                      <Clock size={14} /> Interrupted
                    </span>
                  )}
                  {interaction.usage && (
                    <>
                      <span
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: "4px",
                        }}
                      >
                        <Download size={14} /> In:{" "}
                        {interaction.usage.input_tokens.toLocaleString()}
                      </span>
                      <span
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: "4px",
                        }}
                      >
                        <Upload size={14} /> Out:{" "}
                        {interaction.usage.output_tokens.toLocaleString()}
                      </span>
                    </>
                  )}
                  {result.sql_query && (
                    <button
                      onClick={handleSavePrompt}
                      title="Save as Prompt"
                      style={{
                        background: "none",
                        border: "none",
                        color: "var(--text-tertiary)",
                        cursor: "pointer",
                        display: "flex",
                        alignItems: "center",
                        gap: "4px",
                        padding: 0,
                        marginLeft: "auto"
                      }}
                    >
                      <Save size={14} /> Save Prompt
                    </button>
                  )}
                </div>
              </div>

              {result.sql_query && result.sql_query !== "No SQL queries were executed." && (
                <details className="sql-accordion">
                  <summary>
                    <Code size={14} style={{ marginRight: "8px" }} />
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
                  <div className="chart-toolbar">
                    {[
                      {
                        type: "bar",
                        icon: <BarChartIcon size={14} />,
                        title: "Bar Chart",
                      },
                      {
                        type: "stacked-bar",
                        icon: <StackedIcon size={14} />,
                        title: "Stacked Bar",
                      },
                      {
                        type: "line",
                        icon: <LineChartIcon size={14} />,
                        title: "Line Chart",
                      },
                      {
                        type: "area",
                        icon: <AreaChartIcon size={14} />,
                        title: "Area Chart",
                      },
                      {
                        type: "stacked-area",
                        icon: <StackedIcon size={14} />,
                        title: "Stacked Area",
                      },
                      {
                        type: "pie",
                        icon: <PieChartIcon size={14} />,
                        title: "Pie Chart",
                      },
                      {
                        type: "radar",
                        icon: <RadarIcon size={14} />,
                        title: "Radar Chart",
                      },
                      {
                        type: "composed",
                        icon: <ComposedIcon size={14} />,
                        title: "Composed (Line+Bar)",
                      },
                      {
                        type: "radial",
                        icon: <RadialIcon size={14} />,
                        title: "Radial Chart",
                      },
                      {
                        type: "scatter",
                        icon: <ScatterIcon size={14} />,
                        title: "Scatter Chart",
                      },
                    ].map((btn) => (
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
                        {btn.icon}
                      </button>
                    ))}
                    <div style={{ width: '1px', background: 'var(--border-color)', margin: '4px 0' }} />
                    <button
                      className="chart-tool-btn"
                      onClick={() => setIsChartFullscreen(!isChartFullscreen)}
                      title={isChartFullscreen ? "Exit Fullscreen" : "Enter Fullscreen"}
                    >
                      {isChartFullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
                    </button>
                  </div>
                  <div className="chart-body">
                    <ChartDisplay
                      type={currentChartType || "bar"}
                      config={result.chart_config}
                    />
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
                      className="spinner"
                      size={18}
                      style={{ marginRight: "8px", minWidth: "18px" }}
                    />
                    <span className="status-label">
                      {interaction.status &&
                        interaction.status.startsWith("SQL:")
                        ? "Generating insights from database..."
                        : interaction.status || "Analyzing..."}
                    </span>
                    <RunningTimer />
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
          <SavePromptModal
            isOpen={isSaveModalOpen}
            onClose={() => setIsSaveModalOpen(false)}
            defaultName={interaction.query.slice(0, 50)}
            query={interaction.query}
            sqlCommand={result.sql_query}
            setSavedPrompts={setSavedPrompts}
          />
        )}
      </div>
    );
  },
);

const RunningTimer = () => {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const start = Date.now();
    const interval = setInterval(
      () => setElapsed((Date.now() - start) / 1000),
      100,
    );
    return () => clearInterval(interval);
  }, []);
  return (
    <span
      style={{
        marginLeft: "auto",
        fontSize: "0.8rem",
        color: "var(--text-tertiary)",
        opacity: 0.8,
      }}
    >
      {formatTime(elapsed)}
    </span>
  );
};
