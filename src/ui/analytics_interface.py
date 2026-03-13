"""
Analytics dashboard interface.
"""
import json
from typing import Any, Dict, List

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

from src.core.analytics_service import AnalyticsService


class AnalyticsInterface:
    """Analytics dashboard for the QA Assistant."""
    
    def __init__(self):
        self.analytics_service = AnalyticsService()
    
    def render(self) -> None:
        """Render the analytics dashboard."""
        st.title("Analytics Dashboard")
        
        col1, _ = st.columns([1, 3])
        with col1:
            days = st.selectbox("Time Period", [7, 30, 90], index=1)
        
        analytics_data = self.analytics_service.get_analytics_data(days)
        
        if analytics_data:
            self._render_overview(analytics_data)
            self._render_charts(analytics_data)
            self._render_performance(days)
        else:
            st.info("No analytics data available yet. Start using the chat to see statistics!")
    
    def _render_overview(self, data: Dict[str, Any]) -> None:
        """Render overview metrics."""
        st.write("### Overview Metrics")
        
        feedback_stats = data["feedback_stats"]
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Feedback", feedback_stats[0])
        
        with col2:
            positive_rate = (feedback_stats[1] / feedback_stats[0] * 100) if feedback_stats[0] > 0 else 0
            st.metric("Positive Rate", f"{positive_rate:.1f}%")
        
        with col3:
            st.metric("Negative Feedback", feedback_stats[2])
        
        with col4:
            st.metric("Avg Response Time", f"{data['avg_response_time']:.0f}ms")
    
    def _render_charts(self, data: Dict[str, Any]) -> None:
        """Render analytics charts."""
        st.write("### Performance Charts")
        
        if data["daily_queries"]:
            col1, col2 = st.columns(2)
            
            with col1:
                dates = [row[0] for row in data["daily_queries"]]
                counts = [row[1] for row in data["daily_queries"]]
                
                fig = px.line(
                    x=dates,
                    y=counts,
                    title="Daily Query Volume",
                    labels={"x": "Date", "y": "Queries"},
                )
                fig.update_layout(height=400)
                st.plotly_chart(fig, use_container_width=True)
            
            with col2:
                if data["source_usage"]:
                    sources, counts = self._parse_source_usage(data["source_usage"])
                    if sources:
                        fig = px.pie(
                            values=counts,
                            names=sources,
                            title="Source Usage Distribution",
                        )
                        fig.update_layout(height=400)
                        st.plotly_chart(fig, use_container_width=True)
        
        if data["top_queries"]:
            st.write("#### Top Queries")
            queries = [row[0] for row in data["top_queries"][:5]]
            counts = [row[1] for row in data["top_queries"][:5]]
            
            fig = px.bar(
                x=counts,
                y=queries,
                orientation="h",
                title="Most Frequent Queries",
                labels={"x": "Count", "y": "Query"},
            )
            fig.update_layout(height=400)
            st.plotly_chart(fig, use_container_width=True)
    
    def _parse_source_usage(self, source_usage: List) -> tuple:
        """Parse source usage data for charting."""
        sources = []
        usage_counts = []
        
        for row in source_usage:
            try:
                if isinstance(row[0], str):
                    try:
                        source_data = json.loads(row[0])
                    except json.JSONDecodeError:
                        source_data = [row[0]]
                elif isinstance(row[0], (list, tuple)):
                    source_data = list(row[0])
                else:
                    source_data = [str(row[0])]
                
                for source in source_data:
                    source_str = str(source)
                    if source_str not in sources:
                        sources.append(source_str)
                        usage_counts.append(0)
                    usage_counts[sources.index(source_str)] += row[1]
                    
            except (TypeError, IndexError, AttributeError):
                continue
        
        return sources, usage_counts
    
    def _render_performance(self, days: int) -> None:
        """Render performance metrics."""
        st.write("### Performance Metrics")
        
        data = self.analytics_service.get_performance_metrics(days)
        
        if not data:
            return
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.write("#### Response Time Statistics")
            rt = data["response_time"]
            st.metric("Median", f"{rt['median']:.0f}ms")
            st.metric("95th Percentile", f"{rt['p95']:.0f}ms")
            st.metric("Minimum", f"{rt['min']:.0f}ms")
            st.metric("Maximum", f"{rt['max']:.0f}ms")
        
        with col2:
            st.write("#### Success Rate Statistics")
            sr = data["success_rate"]
            st.metric("Total Queries", sr["total_queries"])
            st.metric("Queries with Feedback", sr["queries_with_feedback"])
            st.metric("Positive Feedback", sr["positive_feedback"])
            st.metric("Success Rate", f"{sr['success_rate']:.1f}%")
        
        st.write("#### Response Time Distribution")
        rt = data["response_time"]
        
        fig = go.Figure()
        fig.add_trace(go.Indicator(
            mode="gauge+number+delta",
            value=rt["median"],
            domain={"x": [0, 1], "y": [0, 1]},
            title={"text": "Median Response Time (ms)"},
            delta={"reference": rt["p95"]},
            gauge={
                "axis": {"range": [None, rt["max"]]},
                "bar": {"color": "darkblue"},
                "steps": [
                    {"range": [0, rt["min"]], "color": "lightgray"},
                    {"range": [rt["min"], rt["median"]], "color": "yellow"},
                    {"range": [rt["median"], rt["p95"]], "color": "orange"},
                    {"range": [rt["p95"], rt["max"]], "color": "red"},
                ],
                "threshold": {
                    "line": {"color": "red", "width": 4},
                    "thickness": 0.75,
                    "value": rt["p95"],
                },
            },
        ))
        fig.update_layout(height=400)
        st.plotly_chart(fig, use_container_width=True)
