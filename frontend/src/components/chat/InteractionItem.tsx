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
  BrainCircuit,
  Coins,
  FileCode2,
  Copy,
} from "lucide-react";
import type { Interaction, SavedPrompt } from "../../types";
import type { ResultBlock } from "../../types";
import { ReportDisplay } from "../data/ReportDisplay";
import { RawDataTable } from "../data/RawDataTable";
import { ChartDisplay } from "../data/ChartDisplay";
import { Timer } from "./Timer";
import { formatTime, formatUsdAsInr } from "../../utils/formatters";
import "../../App.css";

const SavePromptModal = lazy(() => import("../modals/SavePromptModal").then(m => ({ default: m.SavePromptModal })));

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

const hasChartData = (block?: ResultBlock | null) => {
  const data = block?.chart_config?.data;
  return Array.isArray(data) ? data.length > 0 : Boolean(data);
};

interface InteractionItemProps {
  interaction: Interaction;
  idx: number;
  chartOverrides: Record<string, string>;
  setChartOverrides: React.Dispatch<
    React.SetStateAction<Record<string, string>>
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
    const displayBlocks = React.useMemo(() => {
      if (!result) return [];
      const blocks =
        result.result_blocks && result.result_blocks.length > 0
          ? result.result_blocks
          : [
            {
              kind: "text" as const,
              text: result.report,
              chart_config: result.chart_config,
              raw_data: result.raw_data,
            },
          ];
      const hasTextBlock = blocks.some(
        (b) => typeof b?.text === "string" && b.text.trim().length > 0,
      );
      if (!hasTextBlock && typeof result.report === "string" && result.report.trim()) {
        return [{ kind: "text" as const, text: result.report }, ...blocks].filter((b) => {
          const textOk = typeof b?.text === "string" && b.text.trim().length > 0;
          const chartOk = hasChartData(b);
          const tableOk = b?.kind === "table" && Array.isArray(b.raw_data) && b.raw_data.length > 0;
          return textOk || chartOk || tableOk;
        });
      }
      return (blocks as ResultBlock[]).filter((b) => {
        const textOk = typeof b?.text === "string" && b.text.trim().length > 0;
        const chartOk = hasChartData(b);
        const tableOk = b?.kind === "table" && Array.isArray(b.raw_data) && b.raw_data.length > 0;
        return textOk || chartOk || tableOk;
      });
    }, [result]);
    const hasRenderableOutput = React.useMemo(() => {
      if (!result) return false;
      return (displayBlocks as ResultBlock[]).some((b) => {
        const textOk = typeof b.text === "string" && b.text.trim().length > 0;
        const hasChart = hasChartData(b);
        const hasTable = b.kind === "table" && Array.isArray(b.raw_data) && b.raw_data.length > 0;
        return textOk || hasChart || hasTable;
      });
    }, [displayBlocks, result]);
    const [fullscreenChartKey, setFullscreenChartKey] = useState<string | null>(null);
    const [isSaveModalOpen, setIsSaveModalOpen] = useState(false);
    const [sqlModal, setSqlModal] = useState<{ title: string; sql: string } | null>(null);

    // Handle Escape key to close fullscreen chart
    useEffect(() => {
      const handleKeyDown = (e: KeyboardEvent) => {
        if (e.key === "Escape" && fullscreenChartKey) {
          setFullscreenChartKey(null);
        }
      };

      if (fullscreenChartKey) {
        window.addEventListener("keydown", handleKeyDown);
      }
      return () => window.removeEventListener("keydown", handleKeyDown);
    }, [fullscreenChartKey]);

    const handleSavePrompt = () => {
      if (!result?.sql_query) return;
      setIsSaveModalOpen(true);
    };

    const renderSqlButton = (block: ResultBlock, blockIdx: number) => {
      if (!block.sql_query) return null;
      if (block.kind === "table" && (!Array.isArray(block.raw_data) || block.raw_data.length === 0)) return null;
      if (block.kind === "chart" && !hasChartData(block)) return null;
      const label = block.kind === "chart" ? "Chart SQL" : "Raw SQL";
      return (
        <button
          className="block-sql-btn"
          onClick={() =>
            setSqlModal({
              title: block.title || `${label} #${blockIdx + 1}`,
              sql: block.sql_query || "",
            })
          }
          title={`View ${label}`}
        >
          <FileCode2 size={13} />
          SQL
        </button>
      );
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

        {result && hasRenderableOutput && result.report !== "Analyzing..." ? (
          <div className="chat-message ai-message">
            <div className="message-content">
              {displayBlocks.map((block, blockIdx) => (
                <React.Fragment key={`${interaction.id || idx}-block-${blockIdx}`}>
                  {(block.title || block.sql_query) && (
                    <div className="report-block-header">
                      {block.title && <div className="report-block-title">{block.title}</div>}
                      {renderSqlButton(block, blockIdx)}
                    </div>
                  )}
                  {block.text && (
                    <div className="report-text markdown-content">
                      <ReportDisplay text={block.text} />
                    </div>
                  )}
                  {block.chart_config && (
                    <div className={`chart-wrapper-premium ${fullscreenChartKey === `${idx}:${blockIdx}` ? 'fullscreen' : ''}`}>
                      <div className="chart-body">
                        <ChartDisplay
                          type={chartOverrides[`${idx}:${blockIdx}`] || block.chart_config.type || "bar"}
                          config={block.chart_config}
                        />
                      </div>
                      <div className="chart-toolbar">
                        {CHART_TYPES.map((btn) => (
                          <button
                            key={btn.type}
                            className={`chart-tool-btn ${(chartOverrides[`${idx}:${blockIdx}`] || block.chart_config?.type) === btn.type ? "active" : ""}`}
                            onClick={() =>
                              setChartOverrides((prev) => ({
                                ...prev,
                                [`${idx}:${blockIdx}`]: btn.type,
                              }))
                            }
                            title={btn.title}
                          >
                            {React.createElement(btn.icon, { size: 16 })}
                          </button>
                        ))}
                        <div className="chart-divider" />
                        <button
                          className="chart-tool-btn"
                          onClick={() =>
                            setFullscreenChartKey((current) =>
                              current === `${idx}:${blockIdx}` ? null : `${idx}:${blockIdx}`,
                            )
                          }
                          title={fullscreenChartKey === `${idx}:${blockIdx}` ? "Exit Fullscreen" : "Enter Fullscreen"}
                        >
                          {fullscreenChartKey === `${idx}:${blockIdx}` ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
                        </button>
                      </div>
                    </div>
                  )}
                  {block.kind === "table" && Array.isArray(block.raw_data) && block.raw_data.length > 0 && (
                    <>
                      {/* {(typeof block.total_count === "number" || */}
                      {/*   typeof block.row_count === "number" || */}
                      {/*   block.truncated) && ( */}
                      {/*     <div className="table-result-note"> */}
                      {/*       {block.truncated */}
                      {/*         ? `Showing ${block.raw_data.length.toLocaleString()} rows. Full count skipped for speed.` */}
                      {/*         : typeof block.total_count === "number" && block.total_count > block.raw_data.length */}
                      {/*           ? `Showing ${block.raw_data.length.toLocaleString()} of ${block.total_count.toLocaleString()} rows.` */}
                      {/*           : `${(block.total_count ?? block.row_count ?? block.raw_data.length).toLocaleString()} rows.`} */}
                      {/*     </div> */}
                      {/*   )} */}
                      <RawDataTable
                        data={block.raw_data}
                        hasData={true}
                        queryId={interaction.id}
                        truncated={Boolean(block.truncated)}
                        totalCount={block.total_count}
                      />
                    </>
                  )}
                </React.Fragment>
              ))}

              {interaction.thinking && (
                <details className="thinking-accordion persisted">
                  <summary className="thinking-header">
                    <BrainCircuit size={14} />
                    <span>Thinking Process</span>
                  </summary>
                  <div className="thinking-content markdown-content">
                    <ReportDisplay text={interaction.thinking} />
                  </div>
                </details>
              )}

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
                    <span className="report-meta-item" title="Input Tokens">
                      <Download size={14} /> {interaction.usage.input_tokens.toLocaleString()}
                    </span>
                    {interaction.usage.thinking_tokens ? (
                      <span className="report-meta-item" title="Thinking Tokens">
                        <BrainCircuit size={14} /> {interaction.usage.thinking_tokens.toLocaleString()}
                      </span>
                    ) : null}
                    <span className="report-meta-item" title="Output Tokens">
                      <Upload size={14} /> {interaction.usage.output_tokens.toLocaleString()}
                    </span>
                    {interaction.usage.estimated_cost ? (
                      <span className="report-meta-item cost-badge" title="Estimated cost in INR">
                        <Coins size={14} /> {formatUsdAsInr(interaction.usage.estimated_cost)}
                      </span>
                    ) : null}
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
                      {interaction.status || "Analyzing..."}
                    </span>
                    <Timer className="execution-timer" />
                  </summary>
                  {interaction.thinking && (
                    <div className="thinking-content live markdown-content">
                      <ReportDisplay text={interaction.thinking} />
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
        {sqlModal && (
          <div className="sql-modal-backdrop" onClick={() => setSqlModal(null)}>
            <div className="sql-modal" onClick={(e) => e.stopPropagation()}>
              <div className="sql-modal-header">
                <div>
                  <div className="sql-modal-title">{sqlModal.title}</div>
                  <div className="sql-modal-subtitle">Executed SQL</div>
                </div>
                <div className="sql-modal-actions">
                  <button
                    className="sql-modal-action"
                    onClick={() => navigator.clipboard?.writeText(sqlModal.sql)}
                    title="Copy SQL"
                  >
                    <Copy size={14} />
                  </button>
                  <button
                    className="sql-modal-close"
                    onClick={() => setSqlModal(null)}
                    title="Close"
                  >
                    ×
                  </button>
                </div>
              </div>
              <pre className="sql-modal-code">{sqlModal.sql}</pre>
            </div>
          </div>
        )}
      </div>
    );
  },
);
