import React, { useState, useRef, useEffect, useMemo, memo } from "react";
import { Send, Loader2, Square, BarChart3 as BarChartIcon, LineChart as LineChartIcon, PieChart as PieChartIcon, AreaChart as AreaChartIcon, Radar as RadarIcon, ChevronDown, ChevronUp, Copy, Check, Database } from "lucide-react";
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  PieChart,
  Pie,
  AreaChart,
  Area,
  RadarChart,
  Radar,
  ScatterChart,
  Scatter,
  ZAxis,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Cell,
} from "recharts";

interface Interaction {
  id?: number;
  query: string;
  result: any | null;
  status?: string;
}

interface MainContentProps {
  onQuery: (query: string) => void;
  onStop: () => void;
  isLoading: boolean;
  interactions: Interaction[];
}

const COLORS = [
  "#ef4444",
  "#3b82f6",
  "#10b981",
  "#f59e0b",
  "#8b5cf6",
  "#ec4899",
];

const ReportDisplay = memo(({ text }: { text: string }) => {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
  );
});

const RawDataTable = memo(({ data }: { data: any[] }) => {
  if (!data || data.length === 0) return null;
  const columns = Object.keys(data[0]);
  return (
    <div className="raw-data-table-wrapper">
      <details>
        <summary className="raw-data-summary">
          <Database size={16} style={{ marginRight: '8px', opacity: 0.7 }} />
          View Data ({data.length} rows)
        </summary>
        <div className="raw-data-scroll">
          <table className="raw-data-table">
            <thead>
              <tr>
                <th style={{ width: '40px' }}>#</th>
                {columns.map((col) => (
                  <th key={col}>{col.replace(/_/g, ' ')}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.map((row, i) => (
                <tr key={i}>
                  <td style={{ opacity: 0.5, fontSize: '0.75rem' }}>{i + 1}</td>
                  {columns.map((col) => (
                    <td key={col}>{row[col] != null ? String(row[col]) : '—'}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
});

const formatNumber = (num: number) => {
  if (typeof num !== "number") return num;
  if (num >= 1e9) return (num / 1e9).toFixed(1) + "B";
  if (num >= 1e6) return (num / 1e6).toFixed(1) + "M";
  if (num >= 1e4) return (num / 1e3).toFixed(1) + "K";
  return num.toLocaleString();
};

const formatTime = (seconds: number) => {
  if (typeof seconds !== "number") return seconds;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  if (mins < 60) return `${mins}m ${secs}s`;
  const hrs = Math.floor(mins / 60);
  const remainingMins = mins % 60;
  return `${hrs}h ${remainingMins}m`;
};

const highlightSQL = (sql: string) => {
  if (!sql) return "";
  const keywords = [
    "SELECT", "FROM", "WHERE", "GROUP BY", "ORDER BY", "LIMIT", "TOP", 
    "JOIN", "LEFT JOIN", "RIGHT JOIN", "INNER JOIN", "ON", "AND", "OR", 
    "AS", "IN", "NULL", "NOT", "DESC", "ASC", "HAVING", "DISTINCT", 
    "COUNT", "SUM", "AVG", "MIN", "MAX"
  ];
  let highlighted = sql;

  // Highlight strings
  highlighted = highlighted.replace(/'(.*?)'/g, '<span class="sql-string">\'$1\'</span>');

  // Highlight keywords
  keywords.sort((a, b) => b.length - a.length).forEach(kw => {
    const reg = new RegExp(`\\b${kw}\\b`, "gi");
    highlighted = highlighted.replace(reg, `<span class="sql-keyword">${kw.toUpperCase()}</span>`);
  });

  // Highlight numbers
  highlighted = highlighted.replace(/\b(\d+)\b/g, '<span class="sql-number">$1</span>');

  return <span dangerouslySetInnerHTML={{ __html: highlighted }} />;
};

const ChartDisplay = memo(({ type, data }: { type: string, data: any }) => {
  const chartData = useMemo(() => {
    if (!data || !data.labels || !data.datasets) return [];
    return data.labels.map((label: string, index: number) => {
      const item: any = { name: label };
      data.datasets.forEach((ds: any) => {
        item[ds.label] = ds.data[index];
      });
      return item;
    });
  }, [data]);

  if (chartData.length === 0) return null;

  const tooltipStyle = {
    backgroundColor: "var(--bg-surface)",
    borderColor: "var(--border-color)",
    color: "var(--text-primary)",
  };

  if (type === "bar") {
    return (
      <ResponsiveContainer width="100%" height={350}>
        <BarChart data={chartData} margin={{ top: 20, right: 30, left: 20, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" vertical={false} />
          <XAxis dataKey="name" tick={{ fill: "var(--text-secondary)" }} />
          <YAxis tickFormatter={formatNumber} tick={{ fill: "var(--text-secondary)" }} domain={[0, "auto"]} />
          <Tooltip formatter={formatNumber} contentStyle={tooltipStyle} />
          <Legend />
          {data.datasets.map((ds: any, i: number) => (
            <Bar key={ds.label} dataKey={ds.label} fill={COLORS[i % COLORS.length]} radius={[4, 4, 0, 0]} isAnimationActive={false} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    );
  }

  if (type === "line") {
    return (
      <ResponsiveContainer width="100%" height={350}>
        <LineChart data={chartData} margin={{ top: 20, right: 30, left: 20, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" vertical={false} />
          <XAxis dataKey="name" tick={{ fill: "var(--text-secondary)" }} />
          <YAxis tickFormatter={formatNumber} tick={{ fill: "var(--text-secondary)" }} domain={["auto", "auto"]} />
          <Tooltip formatter={formatNumber} contentStyle={tooltipStyle} />
          <Legend />
          {data.datasets.map((ds: any, i: number) => (
            <Line key={ds.label} type="monotone" dataKey={ds.label} stroke={COLORS[i % COLORS.length]} strokeWidth={3} activeDot={{ r: 8 }} isAnimationActive={false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    );
  }

  if (type === "area") {
    return (
      <ResponsiveContainer width="100%" height={350}>
        <AreaChart data={chartData} margin={{ top: 20, right: 30, left: 20, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" vertical={false} />
          <XAxis dataKey="name" tick={{ fill: "var(--text-secondary)" }} />
          <YAxis tickFormatter={formatNumber} tick={{ fill: "var(--text-secondary)" }} domain={[0, "auto"]} />
          <Tooltip formatter={formatNumber} contentStyle={tooltipStyle} />
          <Legend />
          {data.datasets.map((ds: any, i: number) => (
            <Area key={ds.label} type="monotone" dataKey={ds.label} stroke={COLORS[i % COLORS.length]} fill={COLORS[i % COLORS.length]} fillOpacity={0.3} isAnimationActive={false} />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    );
  }

  if (type === "pie" || type === "doughnut") {
    const pieData = data.datasets[0].data.map((val: number, i: number) => ({
      name: data.labels[i],
      value: val,
    }));
    return (
      <ResponsiveContainer width="100%" height={350}>
        <PieChart>
          <Pie
            data={pieData}
            cx="50%"
            cy="50%"
            innerRadius={type === "doughnut" ? 60 : 0}
            outerRadius={80}
            paddingAngle={5}
            dataKey="value"
            label
            isAnimationActive={false}
          >
            {pieData.map((_entry: any, index: number) => (
              <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
            ))}
          </Pie>
          <Tooltip formatter={formatNumber} contentStyle={tooltipStyle} />
          <Legend />
        </PieChart>
      </ResponsiveContainer>
    );
  }

  if (type === "scatter") {
    return (
      <ResponsiveContainer width="100%" height={350}>
        <ScatterChart margin={{ top: 20, right: 30, left: 20, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" />
          <XAxis type="category" dataKey="name" name="category" tick={{ fill: "var(--text-secondary)" }} />
          <YAxis type="number" tickFormatter={formatNumber} tick={{ fill: "var(--text-secondary)" }} domain={["auto", "auto"]} />
          <ZAxis type="number" range={[60, 400]} />
          <Tooltip cursor={{ strokeDasharray: '3 3' }} formatter={formatNumber} contentStyle={tooltipStyle} />
          <Legend />
          {data.datasets.map((ds: any, i: number) => (
            <Scatter key={ds.label} name={ds.label} data={chartData} fill={COLORS[i % COLORS.length]} isAnimationActive={false} />
          ))}
        </ScatterChart>
      </ResponsiveContainer>
    );
  }

  if (type === "radar") {
    return (
      <ResponsiveContainer width="100%" height={350}>
        <RadarChart cx="50%" cy="50%" outerRadius="80%" data={chartData}>
          <PolarGrid stroke="var(--border-color)" />
          <PolarAngleAxis dataKey="name" tick={{ fill: "var(--text-secondary)" }} />
          <PolarRadiusAxis tickFormatter={formatNumber} tick={{ fill: "var(--text-secondary)" }} domain={["auto", "auto"]} />
          <Tooltip formatter={formatNumber} contentStyle={tooltipStyle} />
          <Legend />
          {data.datasets.map((ds: any, i: number) => (
            <Radar key={ds.label} name={ds.label} dataKey={ds.label} stroke={COLORS[i % COLORS.length]} fill={COLORS[i % COLORS.length]} fillOpacity={0.6} isAnimationActive={false} />
          ))}
        </RadarChart>
      </ResponsiveContainer>
    );
  }

  return <div className="report-text">Chart type {type} not supported yet.</div>;
});

const InteractionItem = memo(({ interaction, idx, chartOverrides, setChartOverrides }: any) => {
  const result = interaction.result;
  const currentChartType = chartOverrides[idx] || (result?.chart_config?.type);

  return (
    <div className="interaction-wrapper">
      <div className="chat-message user-message">
        <div className="message-content">{interaction.query}</div>
      </div>

      {result ? (
        <div className="chat-message ai-message">
          <div className="message-content">
            {result.sql_query && (
              <details className="sql-accordion">
                <summary>
                  <Database size={16} style={{ marginRight: '8px', opacity: 0.7 }} />
                  View Executed SQL
                </summary>
                <div style={{ maxHeight: "250px", overflowY: "auto", padding: "var(--space-3) var(--space-4)", backgroundColor: "var(--bg-surface)" }}>
                  <ReactMarkdown
                    components={{
                      code(props) {
                        const { children, className, node, ...rest } = props;
                        const match = /language-(\w+)/.exec(className || '');
                        return match ? (
                          <SyntaxHighlighter
                            {...rest}
                            children={String(children).replace(/\n$/, '')}
                            style={vscDarkPlus}
                            language={match[1]}
                            PreTag="div"
                            wrapLines={true}
                            lineProps={{ style: { whiteSpace: 'pre-wrap', wordBreak: 'break-word' } }}
                            customStyle={{ margin: 0, padding: 0, background: 'transparent', fontSize: '0.875rem' }}
                          />
                        ) : (
                          <code {...rest} className={className}>
                            {children}
                          </code>
                        );
                      }
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
                <div style={{ marginTop: '10px', fontSize: '0.8rem', color: 'var(--text-tertiary)' }}>
                  Generated in {formatTime(result.execution_time)}
                </div>
              )}
            </div>

            {result.raw_data && result.raw_data.length > 1 && (
              <RawDataTable data={result.raw_data} />
            )}

            {result.chart_config && (
              <div className="chart-wrapper-premium">
                <div className="chart-toolbar">
                  {[
                    { type: 'bar', icon: <BarChartIcon size={16} />, title: 'Bar Chart' },
                    { type: 'line', icon: <LineChartIcon size={16} />, title: 'Line Chart' },
                    { type: 'area', icon: <AreaChartIcon size={16} />, title: 'Area Chart' },
                    { type: 'pie', icon: <PieChartIcon size={16} />, title: 'Pie Chart' },
                    { type: 'radar', icon: <RadarIcon size={16} />, title: 'Radar Chart' }
                  ].map(btn => (
                    <button 
                      key={btn.type}
                      className={`chart-tool-btn ${currentChartType === btn.type ? 'active' : ''}`}
                      onClick={() => setChartOverrides((prev: any) => ({...prev, [idx]: btn.type}))}
                      title={btn.title}
                    >
                      {btn.icon}
                    </button>
                  ))}
                </div>
                <div className="chart-body">
                  <ChartDisplay type={currentChartType} data={result.chart_config.data} />
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
                  <Loader2 className="spinner" size={18} style={{ marginRight: '8px' }} />
                  <span>Thinking...</span>
                  <RunningTimer />
                </summary>
                {interaction.status && (
                  <div className="status-text">
                    {interaction.status}
                  </div>
                )}
              </details>
            </div>
          </div>
        </div>
      )}
    </div>
  );
});

const RunningTimer = () => {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const start = Date.now();
    const interval = setInterval(() => setElapsed((Date.now() - start) / 1000), 100);
    return () => clearInterval(interval);
  }, []);
  return (
    <span style={{ marginLeft: "auto", fontSize: "0.8rem", color: "var(--text-tertiary)", opacity: 0.8 }}>
      {formatTime(elapsed)}
    </span>
  );
};

const ChatInputArea = memo(({ onQuery, onStop, isLoading, isInitial }: any) => {
  const [input, setInput] = useState("");
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (isLoading) onStop();
    else if (input.trim()) {
      onQuery(input);
      setInput("");
    }
  };
  return (
    <div className={`input-area ${isInitial ? "input-area-initial" : "input-area-active"}`}>
      <form className="query-container" onSubmit={handleSubmit}>
        <div className="query-input-wrapper">
          <input
            type="text"
            className="query-input"
            placeholder="Ask anything about your data..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
          />
          <button type="submit" className="send-button" disabled={!input.trim() && !isLoading}>
            {isLoading ? <Square size={20} fill="currentColor" /> : <Send size={20} />}
          </button>
        </div>
      </form>
    </div>
  );
});

export const MainContent: React.FC<MainContentProps> = ({
  onQuery,
  onStop,
  isLoading,
  interactions,
}) => {
  const [chartOverrides, setChartOverrides] = useState<Record<number, string>>({});
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [visibleCount, setVisibleCount] = useState(10);

  const paginatedInteractions = useMemo(() => {
    return interactions.slice(-visibleCount);
  }, [interactions, visibleCount]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [paginatedInteractions, isLoading]);

  const isInitial = interactions.length === 0 && !isLoading;

  return (
    <main className="main-content">
      {isInitial ? (
        <div className="center-layout">
          <h1 className="hero-title">Data analytics</h1>
        </div>
      ) : (
        <div className="chat-container">
          <div className="chat-scroll-area">
            {interactions.length > visibleCount && (
              <div style={{ textAlign: 'center', padding: '1rem' }}>
                <button 
                  className="load-more-btn"
                  onClick={() => setVisibleCount(prev => prev + 10)}
                  style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}
                >
                  <ChevronUp size={14} />
                  Load previous messages
                </button>
              </div>
            )}
            {paginatedInteractions.map((interaction, idx) => (
              <InteractionItem 
                key={idx} 
                interaction={interaction} 
                idx={interactions.indexOf(interaction)} 
                chartOverrides={chartOverrides} 
                setChartOverrides={setChartOverrides} 
              />
            ))}
            <div ref={messagesEndRef} />
          </div>
        </div>
      )}

      <ChatInputArea
        onQuery={onQuery}
        onStop={onStop}
        isLoading={isLoading}
        isInitial={isInitial}
      />
    </main>
  );
};
