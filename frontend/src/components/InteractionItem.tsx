import React, { useState, useEffect, memo } from "react";
import {
  Database,
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
} from "lucide-react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import {
  oneDark,
  oneLight,
} from "react-syntax-highlighter/dist/esm/styles/prism";
import type { Interaction } from "../types";
import { ReportDisplay } from "./ReportDisplay";
import { RawDataTable } from "./RawDataTable";
import { ChartDisplay } from "./ChartDisplay";
import { formatTime } from "../utils/formatters";

interface InteractionItemProps {
  interaction: Interaction;
  idx: number;
  chartOverrides: Record<number, string>;
  setChartOverrides: React.Dispatch<
    React.SetStateAction<Record<number, string>>
  >;
  theme: "light" | "dark";
}

export const InteractionItem = memo(
  ({
    interaction,
    idx,
    chartOverrides,
    setChartOverrides,
    theme,
  }: InteractionItemProps) => {
    const result = interaction.result;
    const currentChartType = chartOverrides[idx] || result?.chart_config?.type;

    return (
      <div
        id={`interaction-${interaction.id || idx}`}
        className="interaction-wrapper"
      >
        <div className="chat-message user-message">
          <div className="message-content">{interaction.query}</div>
        </div>

        {result ? (
          <div className="chat-message ai-message">
            <div className="message-content">
              {result.sql_query &&
                !result.sql_query
                  .toLowerCase()
                  .includes("no sql queries were executed") && (
                  <details className="sql-accordion">
                    <summary>
                      <Database
                        size={16}
                        style={{ marginRight: "8px", opacity: 0.7 }}
                      />
                      View Executed SQL
                    </summary>
                    <div className="sql-content-wrapper">
                      {result.sql_query
                        .split(/(?=-- Query \d+)/)
                        .map((queryPart, index) => {
                          const trimmed = queryPart.trim();
                          if (!trimmed) return null;

                          // Try to separate the "-- Query X" header from the actual SQL
                          const match = trimmed.match(
                            /^(-- Query \d+(?: \([^)]+\))?)\s*\n([\s\S]*)$/,
                          );

                          if (match) {
                            const header = match[1];
                            const sql = match[2].trim();
                            return (
                              <div
                                key={index}
                                className="sql-query-block"
                                style={{ marginBottom: "1rem" }}
                              >
                                <div
                                  className="sql-query-header"
                                  style={{
                                    color: "var(--text-tertiary)",
                                    fontSize: "0.85rem",
                                    marginBottom: "8px",
                                    fontFamily: "var(--font-mono)",
                                  }}
                                >
                                  {header}
                                </div>
                                <div
                                  className="sql-query-code"
                                  style={{
                                    backgroundColor:
                                      theme === "dark"
                                        ? "rgba(255,255,255,0.05)"
                                        : "rgba(0,0,0,0.03)",
                                    padding: "12px",
                                    borderRadius: "6px",
                                  }}
                                >
                                  <SyntaxHighlighter
                                    children={sql}
                                    style={
                                      theme === "dark" ? oneDark : oneLight
                                    }
                                    language="sql"
                                    PreTag="div"
                                    wrapLines={true}
                                    lineProps={{
                                      style: {
                                        whiteSpace: "pre-wrap",
                                        wordBreak: "break-word",
                                      },
                                    }}
                                    customStyle={{
                                      margin: 0,
                                      padding: 0,
                                      background: "transparent",
                                      fontSize: "0.875rem",
                                    }}
                                  />
                                </div>
                              </div>
                            );
                          }

                          return (
                            <div
                              key={index}
                              className="sql-query-block"
                              style={{ marginBottom: "1rem" }}
                            >
                              <div
                                className="sql-query-code"
                                style={{
                                  backgroundColor:
                                    theme === "dark"
                                      ? "rgba(255,255,255,0.05)"
                                      : "rgba(0,0,0,0.03)",
                                  padding: "12px",
                                  borderRadius: "6px",
                                }}
                              >
                                <SyntaxHighlighter
                                  children={trimmed}
                                  style={theme === "dark" ? oneDark : oneLight}
                                  language="sql"
                                  PreTag="div"
                                  wrapLines={true}
                                  lineProps={{
                                    style: {
                                      whiteSpace: "pre-wrap",
                                      wordBreak: "break-word",
                                    },
                                  }}
                                  customStyle={{
                                    margin: 0,
                                    padding: 0,
                                    background: "transparent",
                                    fontSize: "0.875rem",
                                  }}
                                />
                              </div>
                            </div>
                          );
                        })}
                    </div>
                  </details>
                )}

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
                  {result.execution_time && (
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
                </div>
              </div>

              {(result.raw_data?.length || 0) > 0 || result.has_data ? (
                <RawDataTable
                  data={result.raw_data || []}
                  hasData={result.has_data}
                  queryId={interaction.id}
                />
              ) : null}

              {result.chart_config && (
                <div className="chart-wrapper-premium">
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
