import React, { useState, useRef, useEffect } from "react";
import { Send, Loader2 } from "lucide-react";
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
}

interface MainContentProps {
  onQuery: (query: string) => void;
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

// Typewriter effect component for the latest message
const TypewriterText = ({
  text,
  isActive,
}: {
  text: string;
  isActive: boolean;
}) => {
  const [displayedText, setDisplayedText] = useState("");

  useEffect(() => {
    if (!isActive) {
      setDisplayedText(text);
      return;
    }

    setDisplayedText("");
    let i = 0;
    const intervalId = setInterval(() => {
      setDisplayedText(text.substring(0, i));
      i++;
      if (i > text.length) {
        clearInterval(intervalId);
      }
    }, 10); // typing speed

    return () => clearInterval(intervalId);
  }, [text, isActive]);

  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]}>{displayedText}</ReactMarkdown>
  );
};

const ChatInputArea = ({
  onQuery,
  isLoading,
  isInitial,
}: {
  onQuery: (query: string) => void;
  isLoading: boolean;
  isInitial: boolean;
}) => {
  const [input, setInput] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (input.trim() && !isLoading) {
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
            placeholder="Ask a question about your data..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={isLoading}
          />
          <button
            type="submit"
            className={`submit-btn ${input.trim() ? "active" : ""}`}
            disabled={!input.trim() || isLoading}
          >
            <Send size={20} />
          </button>
        </div>
      </form>
    </div>
  );
};

export function MainContent({
  onQuery,
  isLoading,
  interactions,
}: MainContentProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [interactions, isLoading]);

  const renderChart = (result: any) => {
    if (!result || !result.chart_config) return null;

    const { type, data } = result.chart_config;
    if (!data || !data.labels || !data.datasets) return null;

    const chartData = data.labels.map((label: string, index: number) => {
      const item: any = { name: label };
      data.datasets.forEach((ds: any) => {
        item[ds.label] = ds.data[index];
      });
      return item;
    });

    if (type === "bar") {
      return (
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={chartData}
            margin={{ top: 20, right: 30, left: 20, bottom: 5 }}
          >
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="var(--border-color)"
              vertical={false}
            />
            <XAxis dataKey="name" tick={{ fill: "var(--text-secondary)" }} />
            <YAxis tick={{ fill: "var(--text-secondary)" }} />
            <Tooltip
              contentStyle={{
                backgroundColor: "var(--bg-surface)",
                borderColor: "var(--border-color)",
                color: "var(--text-primary)",
              }}
            />
            <Legend />
            {data.datasets.map((ds: any, i: number) => (
              <Bar
                key={ds.label}
                dataKey={ds.label}
                fill={COLORS[i % COLORS.length]}
                radius={[4, 4, 0, 0]}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      );
    }

    if (type === "line") {
      return (
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={chartData}
            margin={{ top: 20, right: 30, left: 20, bottom: 5 }}
          >
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="var(--border-color)"
              vertical={false}
            />
            <XAxis dataKey="name" tick={{ fill: "var(--text-secondary)" }} />
            <YAxis tick={{ fill: "var(--text-secondary)" }} />
            <Tooltip
              contentStyle={{
                backgroundColor: "var(--bg-surface)",
                borderColor: "var(--border-color)",
                color: "var(--text-primary)",
              }}
            />
            <Legend />
            {data.datasets.map((ds: any, i: number) => (
              <Line
                key={ds.label}
                type="monotone"
                dataKey={ds.label}
                stroke={COLORS[i % COLORS.length]}
                strokeWidth={3}
                activeDot={{ r: 8 }}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      );
    }

    if (type === "area") {
      return (
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart
            data={chartData}
            margin={{ top: 20, right: 30, left: 20, bottom: 5 }}
          >
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="var(--border-color)"
              vertical={false}
            />
            <XAxis dataKey="name" tick={{ fill: "var(--text-secondary)" }} />
            <YAxis tick={{ fill: "var(--text-secondary)" }} />
            <Tooltip
              contentStyle={{
                backgroundColor: "var(--bg-surface)",
                borderColor: "var(--border-color)",
                color: "var(--text-primary)",
              }}
            />
            <Legend />
            {data.datasets.map((ds: any, i: number) => (
              <Area
                key={ds.label}
                type="monotone"
                dataKey={ds.label}
                fill={COLORS[i % COLORS.length]}
                stroke={COLORS[i % COLORS.length]}
                fillOpacity={0.3}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      );
    }

    if (type === "radar") {
      return (
        <ResponsiveContainer width="100%" height="100%">
          <RadarChart cx="50%" cy="50%" outerRadius="80%" data={chartData}>
            <PolarGrid stroke="var(--border-color)" />
            <PolarAngleAxis
              dataKey="name"
              tick={{ fill: "var(--text-secondary)" }}
            />
            <PolarRadiusAxis tick={{ fill: "var(--text-secondary)" }} />
            <Tooltip
              contentStyle={{
                backgroundColor: "var(--bg-surface)",
                borderColor: "var(--border-color)",
                color: "var(--text-primary)",
              }}
            />
            <Legend />
            {data.datasets.map((ds: any, i: number) => (
              <Radar
                key={ds.label}
                name={ds.label}
                dataKey={ds.label}
                stroke={COLORS[i % COLORS.length]}
                fill={COLORS[i % COLORS.length]}
                fillOpacity={0.6}
              />
            ))}
          </RadarChart>
        </ResponsiveContainer>
      );
    }

    if (type === "pie") {
      const pieData = data.labels.map((label: string, i: number) => ({
        name: label,
        value: data.datasets[0].data[i],
      }));

      return (
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={pieData}
              cx="50%"
              cy="50%"
              labelLine={false}
              label={({ name, percent }) =>
                `${name} ${((percent || 0) * 100).toFixed(0)}%`
              }
              outerRadius={120}
              fill="#8884d8"
              dataKey="value"
            >
              {pieData.map((_: any, index: number) => (
                <Cell
                  key={`cell-${index}`}
                  fill={COLORS[index % COLORS.length]}
                />
              ))}
            </Pie>
            <Tooltip
              contentStyle={{
                backgroundColor: "var(--bg-surface)",
                borderColor: "var(--border-color)",
                color: "var(--text-primary)",
              }}
            />
            <Legend />
          </PieChart>
        </ResponsiveContainer>
      );
    }

    return (
      <div className="report-text">Chart type {type} not supported yet.</div>
    );
  };

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
            {interactions.map((interaction, idx) => (
              <div
                key={idx}
                id={`interaction-${idx}`}
                className="interaction-wrapper"
              >
                {/* User Query */}
                <div className="chat-message user-message">
                  <div className="message-content">{interaction.query}</div>
                </div>

                {/* AI Response */}
                {interaction.result ? (
                  <div className="chat-message ai-message">
                    <div className="message-content">
                      {interaction.result.sql_query && (
                        <details
                          style={{
                            marginBottom: "var(--space-4)",
                            fontSize: "0.875rem",
                          }}
                        >
                          <summary
                            style={{
                              cursor: "pointer",
                              color: "var(--text-secondary)",
                            }}
                          >
                            View Executed SQL
                          </summary>
                          <pre
                            className="sql-code-block"
                            style={{ marginTop: "var(--space-2)" }}
                          >
                            <code>{interaction.result.sql_query}</code>
                          </pre>
                        </details>
                      )}

                      <div className="report-text markdown-content">
                        <TypewriterText
                          text={interaction.result.report}
                          isActive={idx === interactions.length - 1}
                        />
                      </div>

                      {interaction.result.chart_config && (
                        <div className="chart-container">
                          {renderChart(interaction.result)}
                        </div>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="chat-message ai-message">
                    <div className="message-content">
                      <div className="loading-indicator-inline">
                        <Loader2 className="spinner" size={20} />
                        <span>Analyzing data and generating report...</span>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>
        </div>
      )}

      {/* Sticky Input Area */}
      <ChatInputArea 
        onQuery={onQuery} 
        isLoading={isLoading} 
        isInitial={isInitial} 
      />
    </main>
  );
}
