from .CaseDealNodes import BinaryImageLoader, PDFExtractNode, PDFItemExtractor, PDFImageTextExtractor, LLMNode, ReviewFileReader, IDCardOCRNode, JSONKeyExtractor, ShowPrettyText, BusinessPageOCRNode, JsonWrapper, StringToJson, MultilineTextInputAdvanced
from .CaseDealNodes import DiscrepancyIndexSearcher, FinalReportInfoExtractor, OutputFileReader
import os

WEB_DIRECTORY = os.path.join(os.path.dirname(__file__), "web", "extensions")

NODE_CLASS_MAPPINGS = {
    "BinaryImageLoader": BinaryImageLoader,
    "PDFExtractNode": PDFExtractNode,
    "PDFItemExtractor": PDFItemExtractor,
    "PDFImageTextExtractor": PDFImageTextExtractor,
    "LLMNode": LLMNode,
    "ReviewFileReader": ReviewFileReader,
    "IDCardOCRNode": IDCardOCRNode,
    "JSONKeyExtractor": JSONKeyExtractor,
    "ShowPrettyText": ShowPrettyText,
    "BusinessPageOCRNode": BusinessPageOCRNode,
    "JsonWrapper": JsonWrapper,
    "StringToJson": StringToJson,
    "DiscrepancyIndexSearcher": DiscrepancyIndexSearcher,
    "MultilineTextInputAdvanced": MultilineTextInputAdvanced,
    "FinalReportInfoExtractor": FinalReportInfoExtractor,
    "OutputFileReader": OutputFileReader,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MultilineTextInputAdvanced": "📄 多行文本输入节点",
    "BinaryImageLoader": "📄 图片二进制读取器",
    "PDFExtractNode": "🔄 PDF案件材料分割器",
    "PDFItemExtractor": "📄 PDF内容提取器",
    "PDFImageTextExtractor": "📄 PDF图片文字提取器",
    "LLMNode": "💬 LLM节点",
    "ReviewFileReader": "📄 提示词读取器",
    "IDCardOCRNode": "🆔 身份证OCR节点",
    "JSONKeyExtractor": "📄 JSON输出节点",
    "ShowPrettyText": "📄 显示美化文本",
    "BusinessPageOCRNode": "📄 营业执照OCR节点",
    "JsonWrapper": "📄 JSON包装节点",
    "StringToJson": "📄 字符串转JSON节点（需要有特定符号分隔换行）",
    "DiscrepancyIndexSearcher": "🔍 裁量基准搜索器",
    "FinalReportInfoExtractor": "📄 终结报告信息提取器",
    "OutputFileReader": "📄 output目录文件读取器",
}

WEB_DIRECTORY = "./web"

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS', 'WEB_DIRECTORY']
