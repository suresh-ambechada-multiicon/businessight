import React, { useState, useEffect, memo } from "react";
import { Database, Loader2, BarChart3 as BarChartIcon, LineChart as LineChartIcon, PieChart as PieChartIcon, AreaChart as AreaChartIcon, Radar as RadarIcon } from "lucide-react";
import ReactMarkdown from "react-markdown";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark, oneLight } from "react-syntax-highlighter/dist/esm/styles/prism";
import type { Interaction } from "../types";
import { ReportDisplay } from "./ReportDisplay";
import { RawDataTable } from "./RawDataTable";
import { ChartDisplay } from "./ChartDisplay";
import { formatTime } from "../utils/formatters";

interface InteractionItemProps {
  interaction: Interaction;
  idx: number;
  chartOverrides: Record<number, string>;
  setChartOverrides: React.Dispatch<React.SetStateAction<Record<number, string>>>;
  theme: "light" | "dark";
}

export const InteractionItem = memo(
  ({ interaction, idx, chartOverrides, setChartOverrides, theme }: InteractionItemProps) => {
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
              {result.sql_query && (
                <details className="sql-accordion">
                  <summary>
                    <Database
                      size={16}
                      style={{ marginRight: "8px", opacity: 0.7 }}
                    />
                    View Executed SQL
                  </summary>
                  <div
                    style={{
                      maxHeight: "250px",
                      overflowY: "auto",
                      padding: "var(--space-3) var(--space-4)",
                      backgroundColor: "var(--bg-surface)",
                    }}
                  >
                    <ReactMarkdown
                      components={{
                        code(props: any) {
                          const { children, className } = props;
                          const match = /language-(\w+)/.exec(className || "");
                          return match ? (
                            <SyntaxHighlighter
                              children={String(children).replace(/\n$/, "")}
                              style={theme === "dark" ? oneDark : oneLight}
                              language={match[1]}
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
                          ) : (
                            <code className={className}>
                              {children}
                            </code>
                          );
                        },
                      }}
                    >
                      {`\`\`\`sql\n${result.sql_query}\n\`\`\``}
                    </ReactMarkdown>
                  </div>
                </details>
              )}

              <div className="report-text markdown-content">
                <ReportDisplay text={result.report} />
                {result.execution_time && (
                  <div
                    style={{
                      marginTop: "10px",
                      fontSize: "0.8rem",
                      color: "var(--text-tertiary)",
                    }}
                  >
                    Generated in {formatTime(result.execution_time)}
                  </div>
                )}
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
                        icon: <BarChartIcon size={16} />,
                        title: "Bar Chart",
                      },
                      {
                        type: "line",
                        icon: <LineChartIcon size={16} />,
                        title: "Line Chart",
                      },
                      {
                        type: "area",
                        icon: <AreaChartIcon size={16} />,
                        title: "Area Chart",
                      },
                      {
                        type: "pie",
                        icon: <PieChartIcon size={16} />,
                        title: "Pie Chart",
                      },
                      {
                        type: "radar",
                        icon: <RadarIcon size={16} />,
                        title: "Radar Chart",
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
                      data={result.chart_config.data}
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
                      style={{ marginRight: "8px" }}
                    />
                    <span>Thinking...</span>
                    <RunningTimer />
                  </summary>
                  {interaction.status && (
                    <div className="status-text">{interaction.status}</div>
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
