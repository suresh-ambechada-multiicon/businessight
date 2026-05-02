import { useMemo, memo } from "react";
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
import { formatNumber, formatXAxisDate } from "../utils/formatters";

const COLORS = [
  "#ef4444",
  "#3b82f6",
  "#10b981",
  "#f59e0b",
  "#8b5cf6",
  "#ec4899",
];

interface ChartDisplayProps {
  type: string;
  data: any;
}

export const ChartDisplay = memo(({ type, data }: ChartDisplayProps) => {
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
        <BarChart
          data={chartData}
          margin={{ top: 20, right: 30, left: 20, bottom: 5 }}
        >
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="var(--border-color)"
            vertical={false}
          />
          <XAxis
            dataKey="name"
            tickFormatter={formatXAxisDate}
            tick={{ fill: "var(--text-secondary)" }}
          />
          <YAxis
            tickFormatter={formatNumber}
            tick={{ fill: "var(--text-secondary)" }}
            domain={[0, "auto"]}
          />
          <Tooltip formatter={formatNumber} contentStyle={tooltipStyle} />
          <Legend />
          {data.datasets.map((ds: any, i: number) => (
            <Bar
              key={ds.label}
              dataKey={ds.label}
              fill={COLORS[i % COLORS.length]}
              radius={[4, 4, 0, 0]}
              isAnimationActive={false}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    );
  }

  if (type === "line") {
    return (
      <ResponsiveContainer width="100%" height={350}>
        <LineChart
          data={chartData}
          margin={{ top: 20, right: 30, left: 20, bottom: 5 }}
        >
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="var(--border-color)"
            vertical={false}
          />
          <XAxis
            dataKey="name"
            tickFormatter={formatXAxisDate}
            tick={{ fill: "var(--text-secondary)" }}
          />
          <YAxis
            tickFormatter={formatNumber}
            tick={{ fill: "var(--text-secondary)" }}
            domain={["auto", "auto"]}
          />
          <Tooltip formatter={formatNumber} contentStyle={tooltipStyle} />
          <Legend />
          {data.datasets.map((ds: any, i: number) => (
            <Line
              key={ds.label}
              type="monotone"
              dataKey={ds.label}
              stroke={COLORS[i % COLORS.length]}
              strokeWidth={3}
              activeDot={{ r: 8 }}
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    );
  }

  if (type === "area") {
    return (
      <ResponsiveContainer width="100%" height={350}>
        <AreaChart
          data={chartData}
          margin={{ top: 20, right: 30, left: 20, bottom: 5 }}
        >
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="var(--border-color)"
            vertical={false}
          />
          <XAxis
            dataKey="name"
            tickFormatter={formatXAxisDate}
            tick={{ fill: "var(--text-secondary)" }}
          />
          <YAxis
            tickFormatter={formatNumber}
            tick={{ fill: "var(--text-secondary)" }}
            domain={[0, "auto"]}
          />
          <Tooltip formatter={formatNumber} contentStyle={tooltipStyle} />
          <Legend />
          {data.datasets.map((ds: any, i: number) => (
            <Area
              key={ds.label}
              type="monotone"
              dataKey={ds.label}
              stroke={COLORS[i % COLORS.length]}
              fill={COLORS[i % COLORS.length]}
              fillOpacity={0.3}
              isAnimationActive={false}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    );
  }

  if (type === "pie") {
    return (
      <ResponsiveContainer width="100%" height={350}>
        <PieChart>
          <Pie
            data={chartData}
            cx="50%"
            cy="50%"
            labelLine={false}
            label={({ name, percent }) =>
              `${name}: ${(percent ? percent * 100 : 0).toFixed(0)}%`
            }
            outerRadius={80}
            fill="#8884d8"
            dataKey={data.datasets[0].label}
            isAnimationActive={false}
          >
            {chartData.map((_entry: any, index: number) => (
              <Cell
                key={`cell-${index}`}
                fill={COLORS[index % COLORS.length]}
              />
            ))}
          </Pie>
          <Tooltip formatter={formatNumber} contentStyle={tooltipStyle} />
          <Legend />
        </PieChart>
      </ResponsiveContainer>
    );
  }

  if (type === "radar") {
    return (
      <ResponsiveContainer width="100%" height={350}>
        <RadarChart cx="50%" cy="50%" outerRadius="80%" data={chartData}>
          <PolarGrid stroke="var(--border-color)" />
          <PolarAngleAxis dataKey="name" tick={{ fill: "var(--text-secondary)" }} />
          <PolarRadiusAxis tick={{ fill: "var(--text-secondary)" }} />
          {data.datasets.map((ds: any, i: number) => (
            <Radar
              key={ds.label}
              name={ds.label}
              dataKey={ds.label}
              stroke={COLORS[i % COLORS.length]}
              fill={COLORS[i % COLORS.length]}
              fillOpacity={0.6}
              isAnimationActive={false}
            />
          ))}
          <Tooltip formatter={formatNumber} contentStyle={tooltipStyle} />
          <Legend />
        </RadarChart>
      </ResponsiveContainer>
    );
  }

  if (type === "scatter") {
    return (
      <ResponsiveContainer width="100%" height={350}>
        <ScatterChart margin={{ top: 20, right: 30, left: 20, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" />
          <XAxis
            type="category"
            dataKey="name"
            name="category"
            tickFormatter={formatXAxisDate}
            tick={{ fill: "var(--text-secondary)" }}
          />
          <YAxis
            type="number"
            tickFormatter={formatNumber}
            tick={{ fill: "var(--text-secondary)" }}
            domain={["auto", "auto"]}
          />
          <ZAxis type="number" range={[60, 400]} />
          <Tooltip
            cursor={{ strokeDasharray: "3 3" }}
            formatter={formatNumber}
            contentStyle={tooltipStyle}
          />
          <Legend />
          {data.datasets.map((ds: any, i: number) => (
            <Scatter
              key={ds.label}
              name={ds.label}
              data={chartData}
              fill={COLORS[i % COLORS.length]}
              isAnimationActive={false}
            />
          ))}
        </ScatterChart>
      </ResponsiveContainer>
    );
  }

  return (
    <div className="report-text">Chart type {type} not supported yet.</div>
  );
});
