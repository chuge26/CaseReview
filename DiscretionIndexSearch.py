import pandas as pd
import json
import os
from tqdm import tqdm
import numpy as np
from rapidfuzz import fuzz


class DiscretionIndex:
    def __init__(self, data_dir="ReviewAssistant", threshold=60):
        # 设置数据目录路径
        self.data_dir = data_dir
        print(f"数据目录: {self.data_dir}")
        os.makedirs(self.data_dir, exist_ok=True)

        # 设置模糊识别的阈值
        self.threshold = threshold
        print(f"模糊匹配阈值: {self.threshold}")
        
        # 定义裁量索引文件名称
        self.urban_file = "裁量索引-城管.xlsx"
        self.professional_file = "裁量索引-专业.xlsx"
        
        # 验证文件是否存在
        self._check_data_files()

    def _check_data_files(self):
        """检查必要的数据文件是否存在"""
        urban_path = os.path.join(self.data_dir, self.urban_file)
        print(f"城市管理裁量索引文件路径: {urban_path}")
        professional_path = os.path.join(self.data_dir, self.professional_file)
        print(f"专业裁量索引文件路径: {professional_path}")
        
        if not os.path.exists(urban_path):
            raise FileNotFoundError(f"未找到城市管理裁量索引文件: {urban_path}")
        if not os.path.exists(professional_path):
            raise FileNotFoundError(f"未找到专业裁量索引文件: {professional_path}")
        
    @staticmethod
    def is_empty(value):
        """检查值是否为空（包括NaN、None、空字符串或纯空格）"""
        if isinstance(value, (pd.Series, np.ndarray, list)):
            # 如果是数组/Series，检查是否全部为空
            return all(pd.isna(v) or v is None or (isinstance(v, str) and v.strip() == '') for v in value)
        if pd.isna(value) or value is None:
            return True
        if isinstance(value, str) and value.strip() == '':
            return True
        return False

    @staticmethod
    def fill_merged_cells(df, columns_to_fill):
        """
        填充合并单元格导致的空值
        :param df: 原始DataFrame
        :param columns_to_fill: 需要填充空值的列名列表
        :return: 处理后的DataFrame
        """
        for col in columns_to_fill:
            if col not in df.columns:
                continue
                
            # 将空白字符串替换为NA，然后前向填充
            df[col] = df[col].replace(r'^\s*$', pd.NA, regex=True)
            df[col] = df[col].replace('', pd.NA)
            df[col] = df[col].ffill()
        
        return df

    # 找到目标字符串所在的行（模糊匹配，基于相似度）
    # def fuzzy_match(self, row_value, aim_str):
    #     if pd.isna(row_value):  # 忽略空值
    #         return False
    #     print(f"模糊匹配: {row_value} vs {aim_str}")
    #     print(f"相似度: {fuzz.partial_ratio(row_value, aim_str)}")
    #     return fuzz.partial_ratio(row_value, aim_str) >= self.threshold
    
    def process_urban_data(self, aim_str):
        # 定义文件路径
        file_path = os.path.join(self.data_dir, self.urban_file)
        print("正在处理城市管理领域裁量索引文件...")
        
        # 需要继承前一行的列
        inherited_columns = [
            '法律名称', '依据条款', '法律依据', '责任条款',
            '法律责任', '处罚种类', '具体责任', '裁量基准名称及版本'
        ]
        
        # 所有需要的列（按要求的顺序）
        required_columns = [
            '权力事项名称', '违法行为', '法律名称', '依据条款', 
            '法律依据', '责任条款', '法律责任', '处罚种类', 
            '具体责任', '裁量基准名称及版本', '适用情形', 
            '处罚幅度', '处罚下限', '处罚上限'
        ]
        
        # 存储最终结果的字典
        final_result = {}
        
        try:
            # 读取Excel文件
            with pd.ExcelFile(file_path) as xls:
                sheet_names = xls.sheet_names
                
                # 使用tqdm添加进度条
                for sheet_name in tqdm(sheet_names, desc="处理工作表中"):
                    try:
                        # 读取时保留空字符串而不是转换为NaN
                        df = pd.read_excel(xls, sheet_name=sheet_name, keep_default_na=False)
                        
                        # 检查必要的列是否存在
                        if '违法行为' not in df.columns or '适用情形' not in df.columns:
                            tqdm.write(f"工作表 '{sheet_name}' 缺少必要列，跳过")
                            continue
                        
                        # 填充合并单元格导致的空值
                        df = self.fill_merged_cells(df, inherited_columns)
                        
                        # 找到目标字符串所在的行索引（从1开始计数，因为header=0）
                        # match_rows = df[df['违法行为'].str.strip() == aim_str.strip()].index
                        # match_rows = df[df['违法行为'].apply(lambda x: self.fuzzy_match(x, aim_str))].index
                        # 找到模糊匹配度最高的结果
                        df['匹配度'] = df['违法行为'].apply(lambda x: fuzz.partial_ratio(x, aim_str) if not pd.isna(x) else 0)
                        max_score = df['匹配度'].max()
                        
                        if max_score < self.threshold:
                            match_rows = []
                        else:
                            match_rows = df[df['匹配度'] == max_score].index
                        
                        # 删除临时列
                        df.drop(columns=['匹配度'], inplace=True)
                        
                        if len(match_rows) == 0:
                            tqdm.write(f"工作表 '{sheet_name}' 未找到匹配的违法行为，跳过")
                            continue
                            
                        for m in match_rows:
                            # 从m+1行开始查找第一个非空行
                            n = m + 1
                            while n < len(df) and (self.is_empty(df.loc[n, '违法行为']) or df.loc[n, '违法行为'] == df.loc[m, '违法行为']):
                                n += 1
                            
                            # 获取m到n-1行的数据
                            result_rows = df.loc[m:n-1, required_columns].copy()
                            
                            # 如果结果为空则跳过
                            if result_rows.empty:
                                tqdm.write(f"工作表 '{sheet_name}' 匹配行 {m} 但无有效数据，跳过")
                                continue
                                
                            # 重新排序列顺序，将指定列移到前面
                            reordered_columns = ['适用情形', '处罚幅度', '处罚下限', '处罚上限'] + \
                                            [col for col in required_columns 
                                                if col not in ['适用情形', '处罚幅度', '处罚下限', '处罚上限', '权力事项名称', '违法行为']]
                            result_rows = result_rows[reordered_columns]
                            
                            # 将数据转换为字典格式
                            for idx, row in result_rows.iterrows():
                                if self.is_empty(row['适用情形']):
                                    tqdm.write(f"工作表 '{sheet_name}' 行 {idx} 适用情形为空，跳过")
                                    continue
                                
                                key = str(row['适用情形']).strip()
                                row_dict = row.drop('适用情形').to_dict()
                                
                                # 处理空值，保证JSON序列化
                                for k, v in row_dict.items():
                                    if self.is_empty(v):
                                        row_dict[k] = None
                                    elif isinstance(v, str):
                                        row_dict[k] = v.strip()
                                
                                # 添加到最终结果
                                if key not in final_result:
                                    final_result[key] = []
                                final_result[key].append(row_dict)
                    
                    except Exception as e:
                        tqdm.write(f"处理工作表 '{sheet_name}' 时出错: {str(e)}")
                        continue
        
        except Exception as e:
            raise Exception(f"读取Excel文件时出错: {str(e)}")
        
        return json.dumps(final_result, ensure_ascii=False, indent=2)

    def process_professional_data(self, aim_str):
        # 定义文件路径
        file_path = os.path.join(self.data_dir, self.professional_file)
        print("正在处理专业领域裁量索引文件...")
        
        try:
            # 初始化结果字典
            final_result = {}
            law_info_set = []  # 用于存储去重后的法律信息
            
            with pd.ExcelFile(file_path) as xls:
                # 第一步：处理"案由数据"sheet
                print(f"处理文件: {file_path}")
                with tqdm(total=100, desc="处理进度") as pbar:
                    case_df = pd.read_excel(xls, sheet_name='案由数据', keep_default_na=False)
                    
                    # 安全获取数据列
                    required_columns = ['违法行为', '案由编号', '流程领域', '条线', '处罚种类']
                    missing_cols = [col for col in required_columns if col not in case_df.columns]
                    if missing_cols:
                        raise ValueError(f"'案由数据' sheet缺少必要列: {missing_cols}")
                    
                    pbar.update(20)
                    
                    # 找到目标字符串所在的行（模糊匹配）
                    case_df['匹配度'] = case_df['违法行为'].apply(lambda x: fuzz.partial_ratio(x, aim_str) if not pd.isna(x) else 0)
                    max_score = case_df['匹配度'].max()
                    
                    if max_score < self.threshold:
                        match_rows = pd.DataFrame()
                    else:
                        match_rows = case_df[case_df['匹配度'] == max_score]
                        print(f"【匹配结果】: {match_rows.iloc[0]['违法行为']}")
                    
                    # 删除临时列
                    case_df.drop(columns=['匹配度'], inplace=True)
                    
                    if match_rows.empty:
                        print(f"未找到匹配的违法行为: {aim_str}")
                        return {}
                    
                    # 获取第一条匹配记录的基础信息
                    case_info = {
                        '案由编号': match_rows.iloc[0]['案由编号'],
                        '流程领域': match_rows.iloc[0]['流程领域'],
                        '条线': match_rows.iloc[0]['条线'],
                        '处罚种类': match_rows.iloc[0]['处罚种类']
                    }
                    
                    pbar.update(30)
                    
                    # 第二步：处理"法律依据"sheet
                    law_df = pd.read_excel(xls, sheet_name='法律依据', keep_default_na=False)
                    
                    # 确保必要列存在
                    law_required_columns = ['案由编号', '法律名称', '依据条款', '法律依据', '责任条款', '法律责任', '具体责任']
                    missing_law_cols = [col for col in law_required_columns if col not in law_df.columns]
                    if missing_law_cols:
                        raise ValueError(f"'法律依据' sheet缺少必要列: {missing_law_cols}")
                    
                    # 填充合并单元格
                    law_df = self.fill_merged_cells(law_df, law_required_columns)
                    
                    # 获取匹配案由编号的所有法律依据
                    law_records = law_df[law_df['案由编号'] == case_info['案由编号']]
                    legal_basis = []
                    if not law_records.empty:
                        for _, row in law_records.iterrows():
                            if self.is_empty(row['法律依据']):
                                continue
                            
                            law_entry = {
                                '法律名称': row['法律名称'] if not self.is_empty(row['法律名称']) else None,
                                '依据条款': row['依据条款'] if not self.is_empty(row['依据条款']) else None,
                                '法律依据': row['法律依据'] if not self.is_empty(row['法律依据']) else None,
                                '责任条款': row['责任条款'] if not self.is_empty(row['责任条款']) else None,
                                '法律责任': row['法律责任'] if not self.is_empty(row['法律责任']) else None,
                                '具体责任': row['具体责任'] if not self.is_empty(row['具体责任']) else None,
                            }
                            
                            # 去重并生成 LawID
                            if law_entry not in law_info_set:
                                law_info_set.append(law_entry)
                            
                            # 获取 LawID
                            law_id = law_info_set.index(law_entry)
                            legal_basis.append(law_id)
                    
                    pbar.update(20)
                    
                    # 第三步：处理"自由裁量"sheet
                    discretion_df = pd.read_excel(xls, sheet_name='自由裁量', keep_default_na=False)
                    
                    # 确保必要列存在
                    disc_required_columns = ['案由编号', '裁量基准', '适用情形', '处罚幅度', '处罚下限', '处罚上限']
                    missing_disc_cols = [col for col in disc_required_columns if col not in discretion_df.columns]
                    if missing_disc_cols:
                        raise ValueError(f"'自由裁量' sheet缺少必要列: {missing_disc_cols}")
                    
                    # 填充合并单元格
                    discretion_df = self.fill_merged_cells(discretion_df, disc_required_columns)
                    
                    # 获取匹配案由编号的所有裁量记录
                    discretion_records = discretion_df[discretion_df['案由编号'] == case_info['案由编号']]
                    
                    if not discretion_records.empty:
                        for _, row in discretion_records.iterrows():
                            if self.is_empty(row['适用情形']):
                                continue
                            
                            key = str(row['适用情形']).strip()
                            record = {
                                '处罚幅度': row['处罚幅度'] if not self.is_empty(row['处罚幅度']) else None,
                                '处罚下限': row['处罚下限'] if not self.is_empty(row['处罚下限']) else None,
                                '处罚上限': row['处罚上限'] if not self.is_empty(row['处罚上限']) else None,
                                '裁量基准': row['裁量基准'] if not self.is_empty(row['裁量基准']) else None,
                                **case_info,
                                'LawID': legal_basis  # 替换为 LawID
                            }
                            
                            # 安全清理空值并添加记录
                            record = {k: v for k, v in record.items() if not self.is_empty(v)}
                            
                            if key not in final_result:
                                final_result[key] = []
                            final_result[key].append(record)
                    
                    pbar.update(30)
            
            # 将法律信息放到最外层
            output = {
                '法律信息': law_info_set,
                '裁量基准': final_result
            }
            
            return json.dumps(output, ensure_ascii=False, indent=2)
        
        except Exception as e:
            raise Exception(f"处理过程中出错: {str(e)}")

if __name__ == "__main__":
    processor = DiscretionIndex()
    
    aim_str = "未取得施工许可证或者为规避办理施工许可证将工程项目分解后擅自施工"
    print("开始处理数据...")
    with tqdm(total=100) as pbar:
        result_json1 = processor.process_professional_data(aim_str)
        print('result_json1', result_json1)
        result_json2 = processor.process_urban_data(aim_str)
        print('result_json2', result_json2)
        pbar.update(100)
    
    print("\n处理完成！结果如下：")
    print(str(result_json1) + '\n' + str(result_json2))


