import fitz  # PyMuPDF
import numpy as np
from PIL import Image
import sys
import os
import configparser
import requests
from pathlib import Path
import json
from typing import List, Dict, Tuple, Optional, Any
import pytesseract
import torch
import base64
import urllib
from io import BytesIO
import nodes
from nodes import LoadImage
import folder_paths
import comfy
from . import implementOCR
from .DiscretionIndexSearch import DiscretionIndex
import pprint
import re


sys.path.append(os.path.dirname(__file__))   # so .constants and .utils resolve


class BinaryImageLoader:
    """自定义节点：加载图像并输出二进制数据"""
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("STRING", {"default": "", "multiline": False}),
            }
        }
    
    RETURN_TYPES = ("BYTES", "STRING")
    RETURN_NAMES = ("binary_data", "file_path")
    FUNCTION = "load_image"
    CATEGORY = "CaseReview/image/loading"

    def load_image(self, image):
        # 复用ComfyUI原生的图像加载逻辑
        loader = LoadImage()
        image_dict = loader.load_image(image)
        
        # 将张量转换为PIL图像
        tensor = image_dict["image"]
        i = 255. * tensor.cpu().numpy().squeeze()
        img = Image.fromarray(np.clip(i, 0, 255).astype(np.uint8))
        
        # 转换二进制
        if img.mode == 'RGBA':
            img = img.convert('RGB')  # 避免二进制格式复杂化
        
        # 获取二进制数据
        byte_data = img.tobytes()
        
        return (byte_data, image)



class PDFExtractNode:
    """
    Simplified PDF extractor with fixed document types and range processing
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "pdf_document": ("PDF_DOC",),
                "inquire_pages": ("STRING", {"default": "", "description": "调查询问笔录页码 (如 2-5)"}),
                "license_pages": ("STRING", {"default": "", "description": "施工许可证页码"}),
                "id_pages": ("STRING", {"default": "", "description": "身份证页码"}),
                "business_pages": ("STRING", {"default": "", "description": "营业执照页码"}),
                "report_pages": ("STRING", {"default": "", "description": "整改完成报告页码"}),
                "delegation_pages": ("STRING", {"default": "", "description": "授权委托书页码"}),
                "contract_pages": ("STRING", {"default": "", "description": "合同/协议页码"}),
            }
        }

    RETURN_TYPES = ("LIST", "LIST", "LIST", "LIST", "LIST", "LIST", "LIST")
    # RETURN_NAMES = (
    #     "调查询问笔录", "施工许可证", "身份证",
    #     "营业执照", "整改情况", "授权委托书", "合同/协议"
    # )
    RETURN_NAMES = (
        "材料1", "材料2", "材料3",
        "材料4", "材料5", "材料6", "材料7"
    )
    FUNCTION = "process_pdf"
    CATEGORY = "CaseReview/PDF"

    def __init__(self):
        self.add_tesseract_to_path()

    def add_tesseract_to_path(self):
        tesseract_dir = r"D:\Tesseract-OCR"
        if tesseract_dir not in os.environ["PATH"]:
            os.environ["PATH"] = tesseract_dir + ";" + os.environ["PATH"]

    def process_range_str(self, range_str: str, page_count: int) -> List[int]:
        """Parse page range string (e.g., '1-3,5') into actual page numbers"""
        if not range_str.strip():
            return []

        pages = set()
        parts = [p.strip() for p in range_str.split(',') if p.strip()]

        for part in parts:
            if '-' in part:
                start, end = map(int, part.split('-'))
                pages.update(range(max(0, start-1), min(end, page_count)))
            elif part.isdigit():
                page_num = int(part) - 1
                if 0 <= page_num < page_count:
                    pages.add(page_num)
        
        return sorted(pages)

    def extract_pages(self, doc, page_range: str) -> List[Dict]:
        """Extract specified pages from PDF document"""
        if not page_range.strip():
            print("No page range provided, skipping extraction.")
            return []

        page_numbers = self.process_range_str(page_range, len(doc))
        extracted = []
        
        for page_num in page_numbers:
            try:
                page = doc[page_num]
                extracted.append({
                    "page_number": page_num + 1,
                    "content": page.get_text("text"),
                    "page_obj": page
                })
            except Exception as e:
                print(f"Error extracting page {page_num+1}: {str(e)}")
        
        return extracted

    def process_pdf(self, pdf_document, 
                   inquire_pages: str, license_pages: str, id_pages: str,
                   business_pages: str, report_pages: str, delegation_pages: str, 
                   contract_pages: str) -> Tuple[List, ...]:
        """
        Process PDF according to page ranges for each document type
        Returns 7 lists in fixed order
        """
        return (
            self.extract_pages(pdf_document, inquire_pages),    # 调查询问笔录
            self.extract_pages(pdf_document, license_pages),    # 施工许可证
            self.extract_pages(pdf_document, id_pages),         # 身份证
            self.extract_pages(pdf_document, business_pages),   # 营业执照
            self.extract_pages(pdf_document, report_pages),     # 整改完成报告
            self.extract_pages(pdf_document, delegation_pages), # 授权委托书
            self.extract_pages(pdf_document, contract_pages),   # 合同/协议
        )


class PDFItemExtractor:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "pdf_list": ("LIST", {"default": []}),
            }
        }

    RETURN_TYPES = ("STRING", "PDF_DOC")
    RETURN_NAMES = ("pdf文本", "pdf对象")
    FUNCTION = "extract_items"
    CATEGORY = "CaseReview/PDF"

    def extract_items(self, pdf_list: List[Dict]):
        combined_text = ""
        merged_document = fitz.open()  # 仅在外部创建一次

        print("当前pdf共有{}页".format(len(pdf_list)))  # 调试信息

        for item in pdf_list:
            if not isinstance(item, dict):
                continue

            # 处理文本
            text = item.get("content", "")
            if text:
                combined_text += f"第{item['page_number']}页内容:\n{text}\n\n"

            # 处理页面对象
            page_obj = item.get("page_obj")
            if page_obj:
                # 提取单页并插入新文档
                src_doc = page_obj.parent
                temp_doc = fitz.open()
                temp_doc.insert_pdf(src_doc, from_page=page_obj.number, to_page=page_obj.number)
                merged_document.insert_pdf(temp_doc)
                temp_doc.close()  # 关闭临时文档以释放资源

        return (combined_text.strip(), merged_document)


class PDFImageTextExtractor:
    """
    支持多引擎的图片型PDF文字提取器（Tesseract/BaiduOCR）
    自动从config.ini读取百度OCR密钥
    """
    
    CONFIG_FILE = "config.ini"
    DEFAULT_API_KEY = "lle04YnER56ZXFjqi8kj6VeJ"  # 默认公开测试密钥（限500次/天）
    DEFAULT_SECRET_KEY = "ymvGSzG7s7Cs88caRz8Hp5Ot4D1qAfre"
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
            "pdf_document": ("PDF_DOC",),
            "page_range": ("STRING", {"default": "all", "description": "页码范围 (如 '1-3,5' 或 'all')"}),
            "ocr_engine": (["tesseract", "baidu"], {"default": "tesseract"}),
            "language": ("STRING", {"default": "chi_sim+eng", "description": "OCR语言代码（Tesseract使用）"}),
            },
            "optional": {
            "tesseract_path": ("STRING", {
                "default": r"D:\Tesseract-OCR\tesseract.exe" if os.name == 'nt' else "/usr/bin/tesseract",
                "description": "Tesseract可执行文件路径（自动检测系统）"
            }),
            "dpi": ("INT", {"default": 300, "min": 72, "max": 600, "description": "图像DPI"}),
            "config_path": ("STRING", {
                "default": "",
                "description": "自定义config.ini路径（留空则自动查找）"
            }),
            "detect_direction": ("BOOLEAN", {"default": True, "description": "是否检测文字方向"}),
            "paragrap": ("BOOLEAN", {"default": True, "description": "是否合并段落"}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("识别文本",)
    FUNCTION = "extract_text"
    CATEGORY = "CaseReview/OCR"

    def __init__(self):
        self.config = self._load_config()

    def _load_config(self, custom_path: str = "") -> configparser.ConfigParser:
        """加载配置文件，优先级：自定义路径 > 同目录config.ini > 默认密钥"""
        config = configparser.ConfigParser()
        
        # 确保配置节存在
        if not config.has_section('baidu_ocr'):
            config.add_section('baidu_ocr')
        
        # 设置默认值
        config['baidu_ocr']['api_key'] = self.DEFAULT_API_KEY
        config['baidu_ocr']['secret_key'] = self.DEFAULT_SECRET_KEY
        
        # 尝试可能的配置文件路径
        search_paths = []
        if custom_path:
            search_paths.append(Path(custom_path))
        search_paths.extend([
            Path(__file__).parent / self.CONFIG_FILE,
            Path.cwd() / self.CONFIG_FILE
        ])
        
        for cfg_path in search_paths:
            if cfg_path.exists():
                try:
                    config.read(cfg_path, encoding='utf-8')
                    print(f"成功加载配置文件: {cfg_path}")
                    break
                except Exception as e:
                    print(f"配置文件读取失败 {cfg_path}: {str(e)}")
        
        return config

    @staticmethod
    def preprocess_image(img: Image.Image) -> Image.Image:
        """图像预处理流水线"""
        img = img.convert('L')
        img = img.point(lambda x: 0 if x < 128 else 255)  # 二值化
        return img

    def parse_page_range(self, range_str: str, max_pages: int) -> List[int]:
        """解析页码范围字符串"""
        if range_str.lower() == "all":
            return list(range(max_pages))
        
        pages = set()
        for part in range_str.split(','):
            part = part.strip()
            if '-' in part:
                start, end = map(int, part.split('-'))
                pages.update(range(max(0, start-1), min(end, max_pages)))
            elif part.isdigit():
                page_num = int(part) - 1
                if 0 <= page_num < max_pages:
                    pages.add(page_num)
        return sorted(pages)

    def get_baidu_ocr_result(self, image_bytes: bytes, detect_direction, paragrap) -> str:
        """调用BaiduOCR API进行识别"""
        try:
            api_key = self.config.get('baidu_ocr', 'api_key')
            print("api_key:", api_key)
            secret_key = self.config.get('baidu_ocr', 'secret_key')
            print("secret_key:", secret_key)
            
            token_url = "https://aip.baidubce.com/oauth/2.0/token"
            params = {
                "grant_type": "client_credentials",
                "client_id": api_key,
                "client_secret": secret_key
            }
            resp = requests.post(token_url, params=params)
            print("resp.text:", resp.text)  # 调试信息
            resp.raise_for_status()
            access_token = resp.json().get("access_token")
            if not access_token:
                raise ValueError("获取Access Token失败")
            
            base64_data = base64.b64encode(image_bytes).decode('utf-8')
            payload = f'image={urllib.parse.quote_plus(base64_data)}'
            config_set = '&detect_direction={}&paragrap={}'.format(
                'true' if detect_direction else 'false',
                'true' if paragrap else 'false'
            )
            payload = payload + config_set
            
            ocr_url = f"https://aip.baidubce.com/rest/2.0/ocr/v1/accurate_basic?access_token={access_token}"
            headers = {'Content-Type': 'application/x-www-form-urlencoded',
                       'Accept': 'application/json'}
            # response = requests.post(ocr_url, headers=headers, data=payload, timeout=15)
            response = requests.request("POST", ocr_url, headers=headers, data=payload.encode("utf-8"))
            response.raise_for_status()
            print("response.text:", response.text)  # 调试信息
            result = response.json()
            
            return '\n'.join([item['words'] for item in result.get('words_result', [])])
            
        except Exception as e:
            print(f"百度OCR识别失败: {str(e)}")
            return ""

    def extract_text(
        self, 
        pdf_document,
        page_range: str,
        ocr_engine: str,
        language: str,
        tesseract_path: Optional[str] = None,
        dpi: int = 300,
        config_path: str = "",
        detect_direction: bool = True,
        paragrap: bool = True
    ) -> Tuple[str]:
        
        if config_path:
            self.config = self._load_config(config_path)
        
        combined_text = []
        page_numbers = self.parse_page_range(page_range, len(pdf_document))
        
        for page_num in page_numbers:
            try:
                page = pdf_document.load_page(page_num)
                pix = page.get_pixmap(matrix=fitz.Matrix(dpi/72, dpi/72))
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                
                if ocr_engine == "baidu":
                    print(f"正在使用百度OCR识别第 {page_num+1} 页...")
                    img_bytes = self._image_to_bytes(img, format='JPEG')
                    text = self.get_baidu_ocr_result(img_bytes, detect_direction, paragrap)
                else:
                    print(f"正在使用Tesseract识别第 {page_num+1} 页...")
                    if tesseract_path:
                        pytesseract.pytesseract.tesseract_cmd = tesseract_path
                    img = self.preprocess_image(img)
                    text = pytesseract.image_to_string(img, lang=language)
                
                combined_text.append(f"==== 第 {page_num+1} 页 ====\n{text.strip()}\n")
                print(f"第 {page_num+1} 页识别完成")
                
            except Exception as e:
                print(f"处理第 {page_num+1} 页时出错: {str(e)}")
                continue
        combined_text = '\n\n'.join(combined_text).strip()
        return (combined_text,)

    def _image_to_bytes(self, img: Image.Image, format: str = 'JPEG') -> bytes:
        """将PIL图像转为字节流"""
        img_bytes = BytesIO()
        img.save(img_bytes, format=format, quality=95)
        return img_bytes.getvalue()

    

class IDCardOCRNode:
    """
    从身份证pdf提取信息
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "pdf_document": ("PDF_DOC",),
                "page_range": ("STRING", {"default": "all", "description": "页码范围 (如 '1-3,5' 或 'all')"}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("身份证识别结果",)
    FUNCTION = "idcard_ocr"
    CATEGORY = "CaseReview/OCR"

    def parse_page_range(self, range_str: str, max_pages: int) -> List[int]:
        """解析页码范围字符串（支持 'all', '1-3,5' 等格式）"""
        if range_str.lower() == "all":
            return list(range(max_pages))
        
        pages = set()
        for part in range_str.split(','):
            part = part.strip()
            if '-' in part:
                start, end = map(int, part.split('-'))
                pages.update(range(max(0, start-1), min(end, max_pages)))
            elif part.isdigit():
                page_num = int(part) - 1
                if 0 <= page_num < max_pages:
                    pages.add(page_num)
        
        return sorted(pages)

    def idcard_ocr(self, pdf_document, page_range: str) -> str:
        # 解析页码范围
        page_numbers = PDFImageTextExtractor().parse_page_range(page_range, len(pdf_document))
        combined_text = {}
        
        for page_num in page_numbers:
            # 使用DeepSeek IDCard OCR识别
            print("正在对身份证进行OCR识别...")
            response_txt = implementOCR.Ali_IdCardOCRClient().process_pdf_idcard(pdf_document[page_num])
            # combined_text += f"==== 第 {page_num+1} 页 ====\n{response_txt}\n\n"
            combined_text[f"第{page_num+1}页"] = response_txt
            print(f"第 {page_num+1} 页识别完成")
        str_rst = self.translate_en2ch(str(combined_text))
        return (str_rst,)
    
    def translate_en2ch(self, str_dic):
        default_dict = {"name": "姓名",
                        "gender": "性别",
                        "ethnicity": "民族",
                        "birth_date": "出生日期",
                        "address": "住址",
                        "id_number": "身份证号码",
                        "valid_period": "有效日期",
                        "issue_authority": "签发机关",}
        default_key_list = list(default_dict.keys())  # 获取默认字典的所有键
        try:
            for key in default_key_list:
                # 将默认字典的键替换为中文
                str_dic = str_dic.replace(key, default_dict[key])
            # 返回替换后的字典字符串
            return str_dic
        except Exception as e:
           return f"键值对翻译失败: {str(e)}"

class BusinessPageOCRNode:
    """
    从营业执照pdf提取信息
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "pdf_document": ("PDF_DOC",),
                "page_range": ("STRING", {"default": "all", "description": "页码范围 (如 '1-3,5' 或 'all')"}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("营业执照识别结果",)
    FUNCTION = "businesspage_ocr"
    CATEGORY = "CaseReview/OCR"

    def __init__(self):
        self.default_dict = {"validPeriod": "有效期",
                        "businessAddress": "住所",
                        "Capital": "注册资本",
                        "legalPerson": "法定代表人",
                        "RegistrationDate": "注册日期",
                        "companyName": "企业名称",
                        "companyType": "公司类型",
                        "creditCode": "统一社会信用代码",
                        "businessScope": "经营范围",}

    def parse_page_range(self, range_str: str, max_pages: int) -> List[int]:
        """解析页码范围字符串（支持 'all', '1-3,5' 等格式）"""
        if range_str.lower() == "all":
            return list(range(max_pages))
        
        pages = set()
        for part in range_str.split(','):
            part = part.strip()
            if '-' in part:
                start, end = map(int, part.split('-'))
                pages.update(range(max(0, start-1), min(end, max_pages)))
            elif part.isdigit():
                page_num = int(part) - 1
                if 0 <= page_num < max_pages:
                    pages.add(page_num)
        
        return sorted(pages)

    def businesspage_ocr(self, pdf_document, page_range: str) -> str:
        # 解析页码范围
        page_numbers = PDFImageTextExtractor().parse_page_range(page_range, len(pdf_document))
        combined_text = {}
        
        for page_num in page_numbers:
            # 使用DeepSeek IDCard OCR识别
            print("正在对营业执照进行OCR识别...")
            response_txt = implementOCR.Ali_BusinessPageOCRClient().process_pdf_business_license(pdf_document[page_num])
            print("response_txt:", response_txt)
            result_dict = {}
            print("response_txt['Data']:", response_txt['Data'])
            print("type of response_txt['Data']:", type(response_txt['Data']))
            response_data = {}
            try:
                response_data = json.loads(response_txt['Data'])["data"]
                print("response_data:", response_data)
                print("type of response_data:", type(response_data))
            except Exception as e:
                print(f"解析JSON失败: {str(e)}")
                return f"解析JSON失败: {str(e)}"
            if response_data and isinstance(response_data, dict):
                for key in self.default_dict.keys():
                    if key in response_data.keys():
                        result_dict[key] = response_data[key]
            print("result_dict:", result_dict)
            combined_text[f"第{page_num+1}页"] = result_dict
            print(f"第 {page_num+1} 页识别完成")
        print("combined_text:", combined_text)
        str_rst = self.translate_en2ch(str(combined_text))
        return (str_rst,)
    
    def translate_en2ch(self, str_dic):
        default_key_list = list(self.default_dict.keys())  # 获取默认字典的所有键
        try:
            for key in default_key_list:
                # 将默认字典的键替换为中文
                str_dic = str_dic.replace(key, self.default_dict[key])
            print("result_dict_1:", str_dic)
            print("type of result_dict_1:", type(str_dic))
            # 返回替换后的字典字符串
            return str_dic
        except Exception as e:
           return f"键值对翻译失败: {str(e)}"

# class LLMNode:
#     """
#     DeepSeek LLM 调用节点
#     功能：通过API调用DeepSeek模型，支持系统提示词和用户提示词双输入
#     """
    
#     @classmethod
#     def INPUT_TYPES(cls):
#         return {
#             "required": {
#             "user_input": ("STRING", {"default": "", "multiline": True}),
#             },
#             "optional": {
#             "system_prompt": ("STRING", {
#                 "default": "你是一个有帮助的AI助手",
#                 "multiline": True
#             }),
#             "model_name":  (["deepseek-chat", "silicon-QWen3-32B"], {"default": "deepseek-chat"
#             }),
#             "api_key": ("STRING", {
#                 "default": "",
#                 "description": "留空则尝试读取config.ini"
#             }),
#             "api_url": ("STRING", {
#                 "default": "",
#                 "description": "留空则尝试读取config.ini"
#             }),
#             }
#         }

#     RETURN_TYPES = ("STRING",)
#     RETURN_NAMES = ("llm_output",)
#     FUNCTION = "call_llm"
#     CATEGORY = "CaseReview/AI"

#     def __init__(self):
#         self.config_file = Path(__file__).parent / "config.ini"
#         self.config = self._load_config()

#     def _load_config(self) -> dict:
#         """读取配置文件"""
#         config = {
#             "api_url": "",
#             "api_key": "",
#             "temperature": 0.7,
#             "max_tokens": 2048
#         }
        
#         if self.config_file.exists():
#             try:
#                 parser = configparser.ConfigParser()
#                 parser.read(self.config_file)
#                 if "deepseek" in parser:
#                     config.update({
#                         "api_url": parser.get("deepseek", "api_url", fallback=""),
#                         "api_key": parser.get("deepseek", "api_key", fallback=""),
#                         "temperature": parser.getfloat("deepseek", "temperature", fallback=0.7),
#                         "max_tokens": parser.getint("deepseek", "max_tokens", fallback=2048)
#                     })
#             except Exception as e:
#                 print(f"[LLMNode] 配置文件读取失败: {str(e)}")
#         return config

#     def call_llm(self,
#                 user_input: str,
#                 system_prompt: str = "你是一个有帮助的AI助手",
#                 model_name: str = "deepseek-chat",
#                 api_key: Optional[str] = None,
#                 api_url: Optional[str] = None) -> tuple:
#         """
#         调用DeepSeek API
#         参数优先级：直接传入 > config.ini > 代码默认值
#         """
#         # 合并API配置
#         final_api_key = api_key if api_key else self.config["api_key"]
#         final_api_url = api_url if api_url else self.config["api_url"]
        
#         if not final_api_url or not final_api_key:
#             raise ValueError("API配置缺失！请在节点输入或config.ini中设置api_url和api_key")

#         headers = {
#             "Content-Type": "application/json",
#             "Authorization": f"Bearer {final_api_key}"
#         }

#         payload = {
#             "model": model_name,
#             "messages": [
#                 {"role": "system", "content": system_prompt},
#                 {"role": "user", "content": user_input}
#             ],
#             "temperature": self.config["temperature"],
#             "max_tokens": self.config["max_tokens"],
#             "stream": False
#         }

#         if user_input.strip().strip("==== 第 1 页 ===="):
#             try:
#                 print("正在发送信息至LLM...")
#                 print(payload["messages"])
#                 response = requests.post(
#                     final_api_url,
#                     headers=headers,
#                     data=json.dumps(payload),
#                     timeout=30
#                 )
#                 response.raise_for_status()
                
#                 result = response.json()
#                 print("LLM返回结果:", result)
#                 return (result["choices"][0]["message"]["content"],)
            
#             except requests.exceptions.RequestException as e:
#                 error_msg = f"API请求失败: {str(e)}"
#                 if hasattr(e, 'response') and e.response:
#                     error_msg += f" | 状态码: {e.response.status_code} | 响应: {e.response.text}"
#                 raise Exception(error_msg)
#         else:
#             return ("当前页面为空，不调用LLM",)

class LLMNode:
    """
    LLM 调用节点 - 支持DeepSeek和硅基Qwen模型
    功能：通过API调用LLM模型，支持系统提示词和用户提示词双输入
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "user_input": ("STRING", {"default": "", "multiline": True}),
            },
            "optional": {
                "system_prompt": ("STRING", {
                    "default": "你是一个有帮助的AI助手",
                    "multiline": True
                }),
                "model_name": (["deepseek-chat", "Qwen/QwQ-32B"], {
                    "default": "Qwen/QwQ-32B"
                }),
                "api_key": ("STRING", {
                    "default": "",
                    "description": "留空则尝试读取config.ini"
                }),
                "api_url": ("STRING", {
                    "default": "",
                    "description": "留空则尝试读取config.ini"
                }),
                "temperature": ("FLOAT", {
                    "default": 0.7,
                    "min": 0.0,
                    "max": 2.0,
                    "step": 0.1
                }),
                "max_tokens": ("INT", {
                    "default": 2048,
                    "min": 1,
                    "max": 8192,
                    "step": 1
                }),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("llm_output",)
    FUNCTION = "call_llm"
    CATEGORY = "CaseReview/AI"

    def __init__(self):
        self.config_file = Path(__file__).parent / "config.ini"
        self.config = self._load_config()
        self.model_index = {
            "deepseek-chat": 'LLM-deepseek-chat',
            "Qwen/QwQ-32B": 'LLM-siliconflow-Qwen3-32B',
        }
        self.model_configs = {
            "deepseek-chat": {
                "default_url": "https://api.deepseek.com/v1/chat/completions",
                "required_params": ["model", "messages", "temperature", "max_tokens"],
                "response_key_path": ["choices", 0, "message", "content"]
            },
            "Qwen/QwQ-32B": {
                "default_url": "https://api.siliconflow.cn/v1/chat/completions",
                "required_params": ["model", "messages", "temperature", "max_tokens"],
                "response_key_path": ["choices", 0, "message", "content"],
                "additional_params": {
                    "min_p": 0.05,
                    "top_p": 0.7,
                    "top_k": 50,
                    "frequency_penalty": 0.5,
                    "response_format": {"type": "text"},
                    "enable_thinking": True,
                    "thinking_budget": 4096,
                    "stop": [],
                    "n": 1,
                }
            }
        }

    def _load_config(self) -> Dict[str, Any]:
        """读取配置文件"""
        # 初始化配置
        config = {}

        section_list = []
        
        if self.config_file.exists():
            try:
                parser = configparser.ConfigParser()
                parser.read(self.config_file)
                section_list = [sections for sections in parser.sections() if str(sections).startswith('LLM')]  # 获取所有由[]包括的值，形成列表
                # print("LLM-section_list:", section_list)  # 调试信息
                
                for section in section_list:
                    config[section]= {"api_key": "", "api_url": "", "temperature": 0.7, "max_tokens": 2048}
                    for key, value in parser.items(section):
                        if isinstance(config[section][key], float):
                            config[section][key] = parser.getfloat(section, key)
                        elif isinstance(config[section][key], int):
                            config[section][key] = parser.getint(section, key)
                        else:
                            config[section][key] = parser.get(section, key)
            except Exception as e:
                print(f"[LLMNode] 配置文件读取失败: {str(e)}")
            print("LLM-config:", config)  # 调试信息
        return config

    def _build_payload(self, model_name: str, messages: list, temperature: float, max_tokens: int) -> Dict[str, Any]:
        """构建请求负载"""
        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False
        }
        
        # 添加模型特定参数
        if model_name in self.model_configs and "additional_params" in self.model_configs[model_name]:
            payload.update(self.model_configs[model_name]["additional_params"])
        
        return payload

    def call_llm(self,
                user_input: str,
                system_prompt: str = "你是一个有帮助的AI助手",
                model_name: str = "deepseek-chat",
                api_key: Optional[str] = None,
                api_url: Optional[str] = None,
                temperature: Optional[float] = None,
                max_tokens: Optional[int] = None) -> tuple:
        """
        调用LLM API (支持DeepSeek和硅基Qwen)
        参数优先级：直接传入 > config.ini > 代码默认值
        """
        # 合并配置参数
        final_api_key = api_key if api_key else self.config[self.model_index[model_name]].get("api_key", "")
        final_api_url = api_url if api_url else (
            self.config[self.model_index[model_name]].get("api_url", "")
        )
        final_temperature = temperature if temperature is not None else self.config[self.model_index[model_name]].get("temperature", 0.7)
        final_max_tokens = max_tokens if max_tokens is not None else self.config[self.model_index[model_name]].get("max_tokens", 2048)

        print(f"当前模型: {model_name}")
        print(f"API地址: {final_api_url}")
        print(f"当前使用的api_key: {final_api_key}")
        
        # 验证必须参数
        if not final_api_url:
            raise ValueError(f"缺失API地址！请为{model_name}设置api_url")
        if not final_api_key:
            raise ValueError(f"缺失API密钥！请为{model_name}设置api_key")

        # 准备请求数据
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {final_api_key}"
        }

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input}
        ]
        
        payload = self._build_payload(model_name, messages, final_temperature, final_max_tokens)

        if not user_input.strip():
            return ("当前页面为空，不调用LLM",)

        try:
            print(f"正在发送信息至{model_name}...")
            print("请求负载:", json.dumps(payload, indent=2, ensure_ascii=False))
            
            response = requests.post(
                final_api_url,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            
            result = response.json()
            print(f"{model_name}返回结果:", json.dumps(result, indent=2, ensure_ascii=False))
            
            # 从响应中提取结果
            value = result
            for key in self.model_configs[model_name]["response_key_path"]:
                if isinstance(key, int):
                    value = value[key]
                else:
                    value = value[key]
            value = str(value).strip()
            return (value,)
            
        except Exception as e:
            error_msg = f"API请求失败: {str(e)}"
            if hasattr(e, 'response') and e.response:
                error_msg += f" | 状态码: {e.response.status_code} | 响应: {e.response.text}"
            raise Exception(error_msg)


class ReviewFileReader:
    """
    读取ReviewAssistant目录下的txt文件并输出内容
    功能：通过下拉菜单选择文件，自动读取内容
    """
    
    def __init__(self):
        # 设置ReviewAssistant文件夹路径（与节点同目录）
        self.review_dir = Path(__file__).parent / "ReviewAssistant"
        self.review_dir.mkdir(exist_ok=True)  # 如果文件夹不存在则创建
    
    @classmethod
    def INPUT_TYPES(cls):
        # 动态获取文件列表
        file_list = cls._get_file_list()
        
        return {
            "required": {
                "selected_file": (file_list, {"default": file_list[0] if file_list else ""}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("file_content",)
    FUNCTION = "read_file"
    CATEGORY = "CaseReview/Text_Loading"

    @classmethod
    def _get_file_list(cls) -> List[str]:
        """获取ReviewAssistant目录下的所有txt文件"""
        review_dir = Path(__file__).parent / "ReviewAssistant"
        if not review_dir.exists():
            return []
            
        return sorted(
            [f.name for f in review_dir.glob("*.txt") if f.is_file()],
            key=lambda x: x.lower()
        )

    def read_file(self, selected_file: str) -> Tuple[str]:
        """读取选定文件内容"""
        file_path = self.review_dir / selected_file
        
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")
            
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            return (content,)
            
        except Exception as e:
            raise Exception(f"文件读取失败: {str(e)}")


class OutputFileReader:
    """
    读取ComfyUI输出目录下的txt文件并输出内容
    功能：通过下拉菜单选择文件，自动读取内容
    """
    
    def __init__(self):
        # 设置ComfyUI输出文件夹路径
        self.output_dir = Path(__file__).parent.parent.parent / "output"
        self.output_dir.mkdir(exist_ok=True)  # 如果文件夹不存在则创建
    
    @classmethod
    def INPUT_TYPES(cls):
        # 动态获取文件列表
        file_list = cls._get_file_list()
        
        return {
            "required": {
                "selected_file": (file_list, {"default": file_list[0] if file_list else ""}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("file_content",)
    FUNCTION = "read_file"
    CATEGORY = "CaseReview/Text_Loading"

    @classmethod
    def _get_file_list(cls) -> List[str]:
        """获取ComfyUI输出目录下的所有txt文件"""
        output_dir = Path(__file__).parent.parent.parent / "output"
        if not output_dir.exists():
            return []
            
        return sorted(
            [f.name for f in output_dir.glob("*.txt") if f.is_file()],
            key=lambda x: x.lower()
        )

    def read_file(self, selected_file: str) -> Tuple[str]:
        """读取选定文件内容"""
        file_path = self.output_dir / selected_file
        
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")
            
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            return (content,)
            
        except Exception as e:
            raise Exception(f"文件读取失败: {str(e)}")


class JSONKeyExtractor:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text_dict": ("STRING", {"multiline": True, "default": "{'key1': 'value1', 'key2': 'value2'}"}),
                "key_to_extract": ("STRING", {"multiline": False, "default": ""}),
            },
            "optional": {
                "text_input": ("STRING", {"forceInput": True}),
            }
        }
    
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("key&value_output",)
    FUNCTION = "process_dict"
    CATEGORY = "CaseReview/文本处理"

    def get_nested_value(self, data, keys):
        """递归获取嵌套字典中的值"""
        if not keys or not isinstance(data, dict):
            return None
        key = keys[0]
        print("key:", key)
        if key in data:
            if len(keys) == 1:
                return data[key]
            return self.get_nested_value(data[key], keys[1:])
        return None

    def process_dict(self, text_dict, key_to_extract, text_input=None):
        try:
            dict_text = text_input if text_input is not None and text_input != '' else text_dict
            dict_text = dict_text.strip()
            print(f"最终使用的输入文本: {dict_text}")

            if not dict_text or dict_text.strip() == '':
                raise ValueError("输入文本为空")

            if not isinstance(dict_text, str):
                raise ValueError("输入必须是字符串格式的字典")

            dict_text = re.sub(r"(?<!\\)'", '"', dict_text)
            dict_text = dict_text.replace("None", "null")
            data_dict = json.loads(dict_text)
            print(f"解析后的字典: {data_dict}")

            # 支持嵌套键提取
            if key_to_extract:
                keys = key_to_extract.split(".")  # 使用 "." 分隔嵌套路径
                value = self.get_nested_value(data_dict, keys)
                if value is not None:
                    print(f"提取的值: {value}")
                    return (str(value),)

            print("提取失败，返回整个字典的JSON")
            return (json.dumps(data_dict, ensure_ascii=False, indent=2),)

        except json.JSONDecodeError as e:
            print(f"JSON解析错误: {str(e)}")
            return (f"错误: 无法解析字典 - {dict_text}",)
        except Exception as e:
            return (f"错误: {str(e)}",)


class DiscrepancyIndexSearcher:
    # 根据违法行为检索裁量基准
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "violation": ("STRING", {"multiline": True, "default": ""}),
            },
            "optional": {
                "data_dir": ("STRING", {"default": "ReviewAssistant"}),
                "threshold": ("INT", {"default": 60}),
            }
        }
    
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("裁量基准",)
    FUNCTION = "search_index"
    CATEGORY = "CaseReview/案件处理"

    def __init__(self, data_dir="ReviewAssistant"):
        # 使用节点所在目录作为基础路径
        self.node_dir = Path(__file__).parent
        self.data_dir = data_dir
        self.threshold = 60
        self.index_processor = None
        
        # 打印调试信息
        print(f"节点目录: {self.node_dir}")
        print(f"数据目录: {self.data_dir}")
        
        self._init_processor()

    def _init_processor(self):
        """初始化处理器"""
        try:
            full_path = self.node_dir / self.data_dir
            self.index_processor = DiscretionIndex(data_dir=str(full_path), threshold=self.threshold)
            print(f"处理器初始化成功，数据路径: {full_path}\n模糊识别阈值: {self.threshold}")
        except Exception as e:
            self.index_processor = None
            print(f"处理器初始化失败: {str(e)}")

    def search_index(self, violation, **kwargs):
        """搜索裁量基准"""
        try:
            if 'threshold' in kwargs and kwargs['threshold'] != self.threshold:
                self.threshold = int(kwargs['threshold'])
                print(f"阈值变更为: {self.threshold}")
                self._init_processor()  # ⭐⭐ 阈值变化时重新初始化处理器

            # 如果传入了新的data_dir，重新初始化
            if 'data_dir' in kwargs and kwargs['data_dir'] != self.data_dir:
                self.data_dir = kwargs['data_dir']
                self._init_processor()
            
            # 确保处理器可用
            if self.index_processor is None:
                return ("裁量基准检索模块未正确初始化，请检查控制台日志",)
            
            print(f"正在检索裁量基准: {violation}")
            
            # 处理两种裁量数据
            urban_result = self.index_processor.process_urban_data(violation.strip())
            pro_result = self.index_processor.process_professional_data(violation.strip())
            
            # 构建结果字典
            results = {
                "城市管理领域裁量基准": json.loads(urban_result) if urban_result != "{}" else None,
                "专业领域裁量基准": json.loads(pro_result) if pro_result != "{}" else None
            }
            
            # 过滤空结果
            filtered = {k: v for k, v in results.items() if v is not None}
            
            if filtered:
                return (json.dumps(filtered, ensure_ascii=False, indent=2),)
            return ("没有找到相关裁量基准信息",)
            
        except Exception as e:
            error_msg = f"裁量基准检索出错: {str(e)}\n建议调整模糊识别参数后重试"
            print(error_msg)
            return (error_msg,)
        

class FinalReportInfoExtractor:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"multiline": True, "default": ""}),
            },
        }
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("extracted_info",)
    FUNCTION = "extract_info"
    CATEGORY = "CaseReview/案件处理"

    @staticmethod
    def safe_search(pattern, text, flags=0):
        match = re.search(pattern, text, flags)
        return match.group(1).strip() if match else ""

    def extract_info(self, text):
        info = {}
        
        try:
            def safe_search(pattern, text, flags=0):
                match = re.search(pattern, text, flags)
                return match.group(1).strip() if match else ""
            
            info['案由'] = safe_search(r'案由\s+(.+)', text)
            info['立案日期'] = safe_search(r'立案日期\s+(\d{4} 年 \d{2} 月 \d{2} 日)', text)
            info['立案案号'] = safe_search(r'立案案号\s+(.+)', text)
            info['当事人概况'] = safe_search(r'当事人\s+概况\s+(.+)', text)
            info['调查取证主要经过'] = safe_search(r'调查取证\s+主要经过\s+([\s\S]+?)案件主要', text)
            info['案件主要事实情况'] = safe_search(r'案件主要\s+事实情况\s+([\s\S]+?)当事人', text)
            info['当事人意见及争议要点'] = safe_search(r'当事人\s+意见及\s+争议要点\s+([\s\S]+?)主要证据', text)
            info['主要证据'] = safe_search(r'主要证据\s+([\s\S]+?)承办人', text)
            info['承办人处理意见及理由'] = safe_search(r'承办人\s+处理意见\s+及理由\s+([\s\S]+?)承办人签名', text)
            info['报告生成日期'] = safe_search(r'承办人签名：\s+(\d{4} 年 \d{2} 月 \d{2} 日)', text)

            print(f"提取的信息: {info}")  # 调试信息
            
        except Exception as e:
            print(f"Error extracting information: {str(e)}")
            return ("",)  # 返回空字符串而不是空字典
        json_result = json.dumps(info, ensure_ascii=False, indent=4)
        return (str(json_result),)


class MultilineTextInputAdvanced:
    """
    高级多行文本输入节点
    功能：
    1. 保留所有原始文本内容，包括换行符和空白字符
    2. 支持变量替换（格式为 ${变量名}）
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {
                    "multiline": True,
                    "default": "",
                }),
                "old_text": ("STRING", {
                    "multiline": False,
                    "default": "替换前的文本",
                }),
                "new_text": ("STRING", {
                    "multiline": False,
                    "default": "替换后的文本",
                }),
                "replace_all": ("BOOLEAN", {"default": True}),  # True=全部替换 False=只替换第一个
                "case_sensitive": ("BOOLEAN", {"default": False}),  # 是否区分大小写
            },
        }
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "do_replace"
    CATEGORY = "CaseReview/文本处理"
    def do_replace(self, text, old_text, new_text, replace_all, case_sensitive):
        if not old_text:  # 如果旧文本为空则直接返回
            return (text,)
            
        flags = 0 if case_sensitive else re.IGNORECASE
        
        if replace_all:
            text = re.sub(re.escape(old_text), new_text, text, flags=flags)
        else:
            text = re.sub(re.escape(old_text), new_text, text, count=1, flags=flags)
            
        return (text,)


class ShowPrettyText:
    """
    文本显示节点 - 美化显示文本内容
    优化：自动识别JSON/字典/列表等可美化格式，其他保持原样
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"forceInput": True}),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }
    
    INPUT_IS_LIST = True
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "process_text"
    OUTPUT_NODE = True
    OUTPUT_IS_LIST = (False,)
    CATEGORY = "CaseReview/文本处理"
    def process_text(self, text, unique_id=None, extra_pnginfo=None):
        # 获取输入文本(从列表中取出第一个元素)
        input_text = text[0] if text else ""
        print(f"输入文本: {input_text}")  # 调试信息
        # 初始化结果
        result = input_text
        # 尝试解析为JSON/字典/列表
        if input_text.strip().startswith(('{', '[')):
            try:
                parsed_data = json.loads(input_text)
                result = json.dumps(parsed_data, indent=2, ensure_ascii=False)
            except json.JSONDecodeError:
                # JSON解析失败尝试使用pprint
                try:
                    pp = pprint.PrettyPrinter(indent=2, width=80)
                    result = pp.pformat(eval(input_text))
                except:
                    pass
        # 更新节点显示
        if unique_id is not None and extra_pnginfo is not None:
            if hasattr(extra_pnginfo, "workflow"):
                workflow = extra_pnginfo.workflow
            elif isinstance(extra_pnginfo, list) and len(extra_pnginfo) > 0:
                if "workflow" in extra_pnginfo[0]:
                    workflow = extra_pnginfo[0]["workflow"]
            if workflow:
                node = next(
                    (x for x in workflow["nodes"] if str(x["id"]) == str(unique_id)),
                    None,
                )
                if node:
                    node["widgets_values"] = [result]
        # print("result:", result)  # 调试信息
        return {"ui": {"text": [result]}, "result": (result,)}



class JsonWrapper:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"forceInput": True}),
            },
            "optional": {
                "key": ("STRING", {"default": "", "description": "键名"}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("string_json",)
    FUNCTION = "wrap"

    CATEGORY = "CaseReview/文本处理"

    def wrap(self, key, text):
        # 处理key为空的情况
        if not key.strip():
            print("Key is empty, returning text only.")
            return (text,)
        
        # 对文本中的```json进行处理
        text = text.replace("```json", "")
        text = text.replace("```", "")
            
        # 创建key-value对 (可以按照你的需求修改格式)
        key_value = f"{{'{key}': {text}}}"
        return (key_value,)


class StringToJson:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"forceInput": True}),
            },
            "optional": {
                "symbol": ("STRING", {"default": "：", "description": "键名分隔符号"}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("string_json",)
    FUNCTION = "trans"

    CATEGORY = "CaseReview/文本处理"

    def trans(self, symbol, text):
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        result = {}
        key = None

        # 根据分隔符来提取键值对
        for line in lines:
            if symbol in line:
                parts = line.split(symbol, 1)
                key = parts[0].strip()
                value = parts[1].strip() if parts[1].strip() else None
                result[key] = value
            elif key:
                result[key] = f"{result[key]} {line.strip()}" if result[key] else line.strip()
                if not result[key]:
                    result[key] = line.strip()

        # 用于解决多行跟随问题，只取分隔符之后的第一个非空值
        for key in result.keys():
            if isinstance(result[key], str):
                result[key] = result[key].split()[0]
            else:
                pass

        # 提取违法行为
        try:
            pattern = r"对(.*?)的处罚"
            matches = re.findall(pattern, text)
            result["违法行为"] = matches[0].strip() if matches else None
        except Exception as e:
            print("违法行为提取错误-Error:", e)
        
        # 提取案件材料
        try:
            text = ' '.join(text.split())
            print("text:", text)
            # 使用正则表达式匹配材料表格内容
            pattern = r"(\d+)\s+([^\s]+\.pdf)\s+([^\n]+?)\s+([^\n]+?)\s+--\s+([^\s]+)\s+([\d\-]+\s[\d:]+)\s+--"
            matches = re.findall(pattern, text)

            # 构建JSON数据结构
            case_materials = []
            for match in matches:
                material = {
                    "序号": match[0],
                    "材料名称": match[1],
                    "材料说明": match[2].strip(),
                    "备注": match[3].strip(),
                }
                case_materials.append(material)

            print("案件材料:", case_materials)
            # 创建最终的JSON结构
            result["案件材料"] = case_materials

        except Exception as e:
            print("案件材料提取失败-Error:", e)

        json_result = json.dumps(result, ensure_ascii=False, indent=4)
        return (str(json_result),)